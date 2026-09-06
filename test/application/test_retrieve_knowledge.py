"""Behavior of the RetrieveKnowledge use case, observed through ports only."""

import pytest

from application.contracts import RetrieveRequest
from application.errors import ApplicationValidationError
from application.retrieve_knowledge import RetrieveKnowledge
from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from test.doubles import (
    EmbeddingUnavailable,
    FailingEmbeddingModel,
    InMemoryVectorStore,
    RecordingEmbeddingModel,
    StubEmbeddingModel,
    vector_for,
)


def _chunk(
    source_id: str,
    *,
    extra: dict[str, str] | None = None,
    content: str | None = None,
    index: int = 0,
) -> DocumentChunk:
    body = content if content is not None else f"content for {source_id}"
    return DocumentChunk(
        metadata=SourceMetadata(
            SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT),
            title=f"title-{source_id}",
            extra=extra or {},
        ),
        index=index,
        content=body,
    )


def _seed(store: InMemoryVectorStore, *chunks: DocumentChunk) -> None:
    store.upsert(
        [
            EmbeddedChunk(chunk=chunk, vector=vector_for(chunk.content))
            for chunk in chunks
        ]
    )


def _use_case(
    store: InMemoryVectorStore,
    *,
    max_input_length: int = 10_000,
    embedding: object | None = None,
) -> RetrieveKnowledge:
    return RetrieveKnowledge(
        embedding if embedding is not None else StubEmbeddingModel(),  # type: ignore[arg-type]
        store,
        max_input_length=max_input_length,
    )


def test_unfiltered_retrieve_returns_top_k_hits_with_full_provenance() -> None:
    store = InMemoryVectorStore()
    chunk = _chunk("doc-1", extra={"doc_type": "runbook"})
    _seed(store, chunk, _chunk("doc-2"))

    response = _use_case(store).execute(
        RetrieveRequest(query="how to restart", retrieval_limit=1)
    )

    assert len(response.hits) == 1
    hit = response.hits[0]
    assert hit.chunk.source_id == "doc-1"
    assert hit.chunk.reference == SourceReference(
        "doc-1", SourceType.KNOWLEDGE_DOCUMENT
    )
    assert hit.chunk.metadata.title == "title-doc-1"
    assert dict(hit.chunk.metadata.extra) == {"doc_type": "runbook"}
    assert hit.chunk.content == chunk.content
    assert hit.score == 1.0


def test_single_metadata_filter_returns_only_exact_extra_matches() -> None:
    store = InMemoryVectorStore()
    _seed(
        store,
        _chunk("runbook", extra={"doc_type": "runbook"}),
        _chunk("policy", extra={"doc_type": "policy"}),
        _chunk("bare"),
    )

    response = _use_case(store).execute(
        RetrieveRequest(
            query="restart steps",
            retrieval_limit=10,
            metadata_filters={"doc_type": "runbook"},
        )
    )

    assert [hit.chunk.source_id for hit in response.hits] == ["runbook"]


def test_and_filters_require_every_supplied_key() -> None:
    store = InMemoryVectorStore()
    _seed(
        store,
        _chunk("both", extra={"doc_type": "runbook", "severity": "high"}),
        _chunk("type_only", extra={"doc_type": "runbook", "severity": "low"}),
        _chunk("missing_key", extra={"doc_type": "runbook"}),
    )

    response = _use_case(store).execute(
        RetrieveRequest(
            query="urgent runbook",
            retrieval_limit=10,
            metadata_filters={"doc_type": "runbook", "severity": "high"},
        )
    )

    assert [hit.chunk.source_id for hit in response.hits] == ["both"]


def test_missing_filter_key_excludes_chunks() -> None:
    store = InMemoryVectorStore()
    _seed(store, _chunk("no-extra"), _chunk("other", extra={"severity": "high"}))

    response = _use_case(store).execute(
        RetrieveRequest(
            query="find runbook",
            retrieval_limit=10,
            metadata_filters={"doc_type": "runbook"},
        )
    )

    assert response.hits == ()


def test_empty_metadata_filters_match_unfiltered_path() -> None:
    store = InMemoryVectorStore()
    _seed(store, _chunk("a"), _chunk("b"))

    response = _use_case(store).execute(
        RetrieveRequest(query="anything", retrieval_limit=10, metadata_filters={})
    )

    assert [hit.chunk.source_id for hit in response.hits] == ["a", "b"]


def test_filters_apply_before_limit() -> None:
    store = InMemoryVectorStore()
    _seed(
        store,
        _chunk("nearest-non-match", extra={"doc_type": "policy"}),
        _chunk("match-a", extra={"doc_type": "runbook"}),
        _chunk("match-b", extra={"doc_type": "runbook"}),
    )

    response = _use_case(store).execute(
        RetrieveRequest(
            query="runbook",
            retrieval_limit=1,
            metadata_filters={"doc_type": "runbook"},
        )
    )

    assert [hit.chunk.source_id for hit in response.hits] == ["match-a"]


def test_embedding_failure_propagates_without_wrapping() -> None:
    store = InMemoryVectorStore()
    _seed(store, _chunk("doc-1"))
    use_case = RetrieveKnowledge(
        FailingEmbeddingModel(), store, max_input_length=10_000
    )

    with pytest.raises(EmbeddingUnavailable, match="unavailable"):
        use_case.execute(RetrieveRequest(query="anything", retrieval_limit=3))


class _RecordingStore(InMemoryVectorStore):
    def __init__(self) -> None:
        super().__init__()
        self.searches: list[object] = []

    def search(self, vector, limit, *, metadata_filters=None):  # type: ignore[no-untyped-def]
        self.searches.append((vector, limit, metadata_filters))
        return super().search(vector, limit, metadata_filters=metadata_filters)


def test_oversized_query_is_rejected_before_embed_or_store() -> None:
    limit = 20
    store = _RecordingStore()
    _seed(store, _chunk("doc-1"))
    embedder = RecordingEmbeddingModel()
    use_case = _use_case(store, max_input_length=limit, embedding=embedder)

    with pytest.raises(
        ApplicationValidationError,
        match=r"query must be at most 20 characters, got 21",
    ):
        use_case.execute(RetrieveRequest(query="x" * (limit + 1), retrieval_limit=1))

    assert embedder.queries == []
    assert store.searches == []


def test_query_at_exact_max_length_is_accepted() -> None:
    limit = 20
    store = InMemoryVectorStore()
    _seed(store, _chunk("doc-1"))
    embedder = RecordingEmbeddingModel()
    use_case = _use_case(store, max_input_length=limit, embedding=embedder)
    query = "x" * limit

    response = use_case.execute(RetrieveRequest(query=query, retrieval_limit=1))

    assert embedder.queries == [query]
    assert len(response.hits) == 1
