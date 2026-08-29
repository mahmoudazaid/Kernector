"""Behavior of RewriteAndRetrieveKnowledge, observed through ports only."""

import pytest

from application.contracts import RetrieveRequest
from application.retrieve_knowledge import RetrieveKnowledge
from application.rewrite_and_retrieve import (
    QueryRewriteFailure,
    RewriteAndRetrieveKnowledge,
)
from domain.errors import QueryRewriterError
from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from test.doubles import (
    BlankQueryRewriter,
    FailingQueryRewriter,
    InMemoryVectorStore,
    RecordingEmbeddingModel,
    StubQueryRewriter,
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
    rewritten: str = "payment service failure last week",
    embedder: RecordingEmbeddingModel | None = None,
    rewriter: object | None = None,
) -> tuple[RewriteAndRetrieveKnowledge, RecordingEmbeddingModel]:
    recording = embedder if embedder is not None else RecordingEmbeddingModel()
    retrieve = RetrieveKnowledge(recording, store)
    query_rewriter = (
        rewriter if rewriter is not None else StubQueryRewriter(rewritten)
    )
    return (
        RewriteAndRetrieveKnowledge(query_rewriter, retrieve),  # type: ignore[arg-type]
        recording,
    )


def test_rewritten_query_is_embedded_and_both_queries_are_observable() -> None:
    store = InMemoryVectorStore()
    _seed(store, _chunk("doc-1"), _chunk("doc-2"))
    original = "what broke?"
    rewritten = "payment service failure last week"
    use_case, embedder = _use_case(store, rewritten=rewritten)

    response = use_case.execute(
        RetrieveRequest(query=original, retrieval_limit=2)
    )

    assert embedder.queries == [rewritten]
    assert response.original_query == original
    assert response.rewritten_query == rewritten
    assert len(response.hits) == 2


def test_retrieval_limit_and_metadata_filters_pass_through_unchanged() -> None:
    store = InMemoryVectorStore()
    _seed(
        store,
        _chunk("runbook", extra={"doc_type": "runbook"}),
        _chunk("policy", extra={"doc_type": "policy"}),
        _chunk("runbook-2", extra={"doc_type": "runbook"}),
    )
    use_case, _ = _use_case(store, rewritten="restart payment service")

    response = use_case.execute(
        RetrieveRequest(
            query="how do we restart?",
            retrieval_limit=1,
            metadata_filters={"doc_type": "runbook"},
        )
    )

    assert [hit.chunk.source_id for hit in response.hits] == ["runbook"]


def test_query_rewriter_error_surfaces_as_query_rewrite_failure() -> None:
    store = InMemoryVectorStore()
    _seed(store, _chunk("doc-1"))
    use_case, embedder = _use_case(
        store, rewriter=FailingQueryRewriter()
    )

    with pytest.raises(QueryRewriteFailure, match="unavailable") as raised:
        use_case.execute(RetrieveRequest(query="what broke?", retrieval_limit=1))

    assert isinstance(raised.value.__cause__, QueryRewriterError)
    assert embedder.queries == []


def test_blank_rewrite_surfaces_as_query_rewrite_failure() -> None:
    store = InMemoryVectorStore()
    _seed(store, _chunk("doc-1"))
    use_case, embedder = _use_case(store, rewriter=BlankQueryRewriter())

    with pytest.raises(QueryRewriteFailure, match="blank"):
        use_case.execute(RetrieveRequest(query="what broke?", retrieval_limit=1))

    assert embedder.queries == []


def test_unrelated_exception_propagates_unwrapped() -> None:
    class BoomRewriter:
        def rewrite(self, query: str) -> str:
            raise ValueError("not a rewrite error")

    store = InMemoryVectorStore()
    use_case, embedder = _use_case(store, rewriter=BoomRewriter())

    with pytest.raises(ValueError, match="not a rewrite error"):
        use_case.execute(RetrieveRequest(query="what broke?", retrieval_limit=1))

    assert embedder.queries == []
