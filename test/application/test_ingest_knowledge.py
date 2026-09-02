"""Behavior of the IngestKnowledge use case, observed through ports only."""

import logging

import pytest

from application import observability
from application.contracts import IngestRequest
from application.errors import ApplicationValidationError
from application.ingest_knowledge import IngestFailure, IngestKnowledge
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from test.doubles import (
    EmbeddingUnavailable,
    FailingEmbeddingModel,
    InMemoryVectorStore,
    StubEmbeddingModel,
    WrongLengthEmbeddingModel,
    vector_for,
)
from test.log_record import flatten_log_record, operation_records
CHUNK_SIZE = 10
CHUNK_OVERLAP = 2
# 26 characters. Size 10 with overlap 2 gives step 8, so the windows are
# [0:10], [8:18], [16:26] -> exactly 3 chunks, the last one filling the tail.
CONTENT = "abcdefghijklmnopqrstuvwxyz"


def _document(
    source_id: str = "doc-1",
    content: str = CONTENT,
    *,
    source_type: str = SourceType.KNOWLEDGE_DOCUMENT,
) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(SourceReference(source_id, source_type)),
        content,
    )


def _use_case(
    store: InMemoryVectorStore,
    *,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> IngestKnowledge:
    return IngestKnowledge(
        StubEmbeddingModel(),
        store,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


def test_a_single_document_is_chunked_embedded_and_stored() -> None:
    store = InMemoryVectorStore()

    response = _use_case(store).execute(IngestRequest(documents=[_document()]))

    assert response.accepted_ids == ("doc-1",)
    assert response.chunk_count == 3
    assert len(store.records) == 3


def test_every_stored_chunk_is_paired_with_its_own_vector() -> None:
    store = InMemoryVectorStore()

    _use_case(store).execute(IngestRequest(documents=[_document()]))

    # The three windows of CONTENT at size 10 / overlap 2, sliced by hand.
    expected = {0: "abcdefghij", 1: "ijklmnopqr", 2: "qrstuvwxyz"}
    stored = {record.chunk.index: record for record in store.records.values()}

    assert stored.keys() == expected.keys()
    for index, content in expected.items():
        assert stored[index].chunk.content == content
        assert list(stored[index].vector) == vector_for(content)


@pytest.mark.parametrize("offset", [-1, 1])
def test_a_wrong_length_embedding_result_is_rejected_before_any_write(
    offset: int,
) -> None:
    store = InMemoryVectorStore()
    use_case = IngestKnowledge(
        WrongLengthEmbeddingModel(offset),
        store,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )

    with pytest.raises(ApplicationValidationError, match="embedding"):
        use_case.execute(IngestRequest(documents=[_document()]))

    assert store.records == {}


def test_duplicate_source_references_in_one_request_are_rejected() -> None:
    store = InMemoryVectorStore()

    with pytest.raises(ApplicationValidationError, match="duplicate"):
        _use_case(store).execute(
            IngestRequest(documents=[_document(), _document(content="other body")])
        )

    assert store.records == {}


def test_the_same_source_id_under_two_source_types_is_not_a_duplicate() -> None:
    store = InMemoryVectorStore()

    response = _use_case(store).execute(
        IngestRequest(
            documents=[
                _document("shared", source_type="knowledge_document"),
                _document("shared", source_type="connector_feed"),
            ]
        )
    )

    assert response.accepted_ids == ("shared", "shared")
    assert len(store.records) == 6
    kinds = {key[0] for key in store.records}
    assert kinds == {"knowledge_document", "connector_feed"}


def test_deletion_is_scoped_to_the_complete_source_reference() -> None:
    store = InMemoryVectorStore()
    _use_case(store).execute(
        IngestRequest(
            documents=[
                _document("shared", source_type="knowledge_document"),
                _document("shared", source_type="connector_feed"),
            ]
        )
    )
    assert len(store.records) == 6

    _use_case(store, chunk_size=30, chunk_overlap=0).execute(
        IngestRequest(
            documents=[_document("shared", source_type="knowledge_document")]
        )
    )

    # knowledge_document collapsed to one chunk; connector_feed's three survive.
    assert len(store.records) == 4
    assert sorted(
        (key[0], key[1], key[2]) for key in store.records
    ) == [
        ("connector_feed", "shared", 0),
        ("connector_feed", "shared", 1),
        ("connector_feed", "shared", 2),
        ("knowledge_document", "shared", 0),
    ]


def test_re_ingesting_with_fewer_chunks_removes_the_stale_ones() -> None:
    store = InMemoryVectorStore()
    request = IngestRequest(documents=[_document()])
    _use_case(store).execute(request)
    assert len(store.records) == 3

    # CONTENT is 26 characters, so a 30-character window yields one chunk.
    response = _use_case(store, chunk_size=30, chunk_overlap=0).execute(request)

    assert response.chunk_count == 1
    assert len(store.records) == 1
    assert [record.chunk.index for record in store.records.values()] == [0]


def test_re_ingesting_unchanged_content_converges_on_the_same_count() -> None:
    store = InMemoryVectorStore()
    request = IngestRequest(documents=[_document()])

    first = _use_case(store).execute(request)
    second = _use_case(store).execute(request)

    assert first.chunk_count == 3
    assert second.chunk_count == 3
    assert len(store.records) == 3


def test_re_ingesting_one_source_leaves_other_sources_untouched() -> None:
    store = InMemoryVectorStore()
    _use_case(store).execute(
        IngestRequest(documents=[_document("doc-1"), _document("doc-2")])
    )
    assert len(store.records) == 6

    _use_case(store, chunk_size=30, chunk_overlap=0).execute(
        IngestRequest(documents=[_document("doc-1")])
    )

    # doc-1 collapsed to one chunk; doc-2's three are absent from the request
    # and must survive untouched: 1 + 3.
    assert len(store.records) == 4
    assert sorted(
        (record.chunk.reference.source_id, record.chunk.index)
        for record in store.records.values()
    ) == [("doc-1", 0), ("doc-2", 0), ("doc-2", 1), ("doc-2", 2)]


def test_an_embedding_failure_preserves_previously_stored_data() -> None:
    store = InMemoryVectorStore()
    _use_case(store).execute(IngestRequest(documents=[_document()]))
    before = dict(store.records)
    assert len(before) == 3

    failing = IngestKnowledge(
        FailingEmbeddingModel(),
        store,
        chunk_size=30,
        chunk_overlap=0,
    )
    with pytest.raises(IngestFailure) as raised:
        failing.execute(IngestRequest(documents=[_document()]))

    assert raised.value.vector_mutation_started is False
    assert isinstance(raised.value.__cause__, EmbeddingUnavailable)
    assert store.records == before


def test_ingest_success_logs_counts_without_document_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = InMemoryVectorStore()
    secret = "CONFIDENTIAL_" + CONTENT  # same chunk geometry as CONTENT → 3 chunks
    observability.bind_request_id("req-ingest-1")
    try:
        with caplog.at_level(logging.INFO, logger="application.ingest_knowledge"):
            response = _use_case(store).execute(
                IngestRequest(documents=[_document(content=secret)])
            )
    finally:
        observability.clear_request_id()

    records = operation_records(caplog.records, operation="ingest")
    assert len(records) == 1
    message = records[0].getMessage()
    assert "outcome=success" in message
    assert "request_id=req-ingest-1" in message
    assert "source_count=1" in message
    assert f"chunk_count={response.chunk_count}" in message
    assert "source_type=knowledge_document" in message
    flat = flatten_log_record(records[0])
    assert secret not in flat
    assert "CONFIDENTIAL_" not in flat


def test_ingest_failure_logs_error_type_without_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = InMemoryVectorStore()
    failing = IngestKnowledge(
        FailingEmbeddingModel(),
        store,
        chunk_size=30,
        chunk_overlap=0,
    )
    with caplog.at_level(logging.ERROR, logger="application.ingest_knowledge"):
        with pytest.raises(IngestFailure) as raised:
            failing.execute(
                IngestRequest(
                    documents=[_document(content="abcdefghijklmnopqrstuvwxyz")]
                )
            )

    leak = str(raised.value)
    records = operation_records(caplog.records, operation="ingest")
    assert len(records) == 1
    message = records[0].getMessage()
    assert "outcome=error" in message
    assert "error_type=IngestFailure" in message
    assert records[0].exc_info is None
    flat = flatten_log_record(records[0])
    assert leak not in flat
    assert "abcdefghijklmnopqrstuvwxyz" not in flat
