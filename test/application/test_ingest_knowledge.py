"""Behavior of the IngestKnowledge use case, observed through ports only."""

import pytest

from application.contracts import IngestRequest
from application.errors import ApplicationValidationError
from application.ingest_knowledge import IngestFailure, IngestKnowledge
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
    Ticket,
)
from test.doubles import (
    EmbeddingUnavailable,
    FailingEmbeddingModel,
    InMemoryVectorStore,
    StubEmbeddingModel,
    WrongLengthEmbeddingModel,
    vector_for,
)

CHUNK_SIZE = 10
CHUNK_OVERLAP = 2
# 26 characters. Size 10 with overlap 2 gives step 8, so the windows are
# [0:10], [8:18], [16:26] -> exactly 3 chunks, the last one filling the tail.
CONTENT = "abcdefghijklmnopqrstuvwxyz"


def _document(source_id: str = "doc-1", content: str = CONTENT) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)),
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
    """Identity is the complete SourceReference, not `source_id` alone."""
    store = InMemoryVectorStore()
    ticket_typed = SourceDocument(
        SourceMetadata(SourceReference("doc-1", SourceType.TICKET)),
        CONTENT,
    )

    response = _use_case(store).execute(
        IngestRequest(documents=[_document("doc-1"), ticket_typed])
    )

    # 3 chunks each, and the two references are distinct, so nothing collides.
    assert response.chunk_count == 6
    assert len(store.records) == 6


def test_a_non_empty_tickets_collection_is_rejected() -> None:
    store = InMemoryVectorStore()

    with pytest.raises(ApplicationValidationError, match="tickets"):
        _use_case(store).execute(
            IngestRequest(tickets=[Ticket("KRN-1", "ticket body")])
        )

    assert store.records == {}


def test_tickets_are_rejected_before_any_accompanying_document_is_stored() -> None:
    """Never silently dropped: a partial ingest would be worse than an error."""
    store = InMemoryVectorStore()

    with pytest.raises(ApplicationValidationError, match="tickets"):
        _use_case(store).execute(
            IngestRequest(
                documents=[_document()],
                tickets=[Ticket("KRN-1", "ticket body")],
            )
        )

    assert store.records == {}


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


def test_deletion_is_scoped_to_the_complete_source_reference() -> None:
    """A re-ingest must not delete the same id under another source type."""
    store = InMemoryVectorStore()
    ticket_typed = SourceDocument(
        SourceMetadata(SourceReference("doc-1", SourceType.TICKET)),
        CONTENT,
    )
    _use_case(store).execute(
        IngestRequest(documents=[_document("doc-1"), ticket_typed])
    )
    assert len(store.records) == 6

    _use_case(store, chunk_size=30, chunk_overlap=0).execute(
        IngestRequest(documents=[_document("doc-1")])
    )

    # The knowledge_document copy collapsed to one chunk; the ticket-typed
    # copy of the same id keeps all three: 1 + 3.
    assert len(store.records) == 4
    assert sorted(
        (str(record.chunk.reference.source_type), record.chunk.index)
        for record in store.records.values()
    ) == [("knowledge_document", 0), ("ticket", 0), ("ticket", 1), ("ticket", 2)]


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
