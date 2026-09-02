"""Hybrid retrieve behavior on RetrieveKnowledge (ports only)."""

from collections.abc import Mapping, Sequence

import pytest

from application.contracts import RetrieveRequest
from application.retrieve_knowledge import RetrieveKnowledge
from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
    Vector,
)
from test.doubles import (
    InMemoryLexicalIndex,
    InMemoryVectorStore,
    StubEmbeddingModel,
    vector_for,
)


def _chunk(
    source_id: str,
    content: str,
    *,
    extra: dict[str, str] | None = None,
    index: int = 0,
) -> DocumentChunk:
    return DocumentChunk(
        metadata=SourceMetadata(
            SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT),
            title=f"title-{source_id}",
            extra=extra or {},
        ),
        index=index,
        content=content,
    )


def _embed(chunk: DocumentChunk) -> EmbeddedChunk:
    return EmbeddedChunk(chunk=chunk, vector=vector_for(chunk.content))


class _ScriptedVectorStore:
    """Returns a fixed hit list regardless of the query vector."""

    def __init__(self, hits: Sequence[ScoredChunk]) -> None:
        self._hits = tuple(hits)
        self.searches: list[tuple[object, int, object]] = []

    def upsert(self, embedded: Sequence[EmbeddedChunk]) -> None:
        return None

    def search(
        self,
        vector: Vector,
        limit: int,
        *,
        metadata_filters: Mapping[str, str] | None = None,
    ) -> Sequence[ScoredChunk]:
        self.searches.append((vector, limit, metadata_filters))
        if limit <= 0:
            return ()
        filters = metadata_filters or {}
        matched = [
            hit
            for hit in self._hits
            if not filters
            or all(
                hit.chunk.metadata.extra.get(key) == value
                for key, value in filters.items()
            )
        ]
        return tuple(matched[:limit])

    def delete_source(self, reference: SourceReference) -> None:
        return None


class _RecordingLexicalIndex(InMemoryLexicalIndex):
    def __init__(self) -> None:
        super().__init__()
        self.searches: list[tuple[str, int, object]] = []

    def search(
        self,
        query: str,
        limit: int,
        *,
        metadata_filters: Mapping[str, str] | None = None,
    ) -> Sequence[ScoredChunk]:
        self.searches.append((query, limit, metadata_filters))
        return super().search(query, limit, metadata_filters=metadata_filters)


def test_hybrid_off_matches_vector_only_ranking() -> None:
    chunk_a = _chunk("a", "vector favorite paraphrase")
    chunk_b = _chunk("b", "ERR-4021 exact token")
    vector = _ScriptedVectorStore(
        [
            ScoredChunk(chunk=chunk_a, score=0.9),
            ScoredChunk(chunk=chunk_b, score=0.2),
        ]
    )
    lexical = InMemoryLexicalIndex()
    lexical.upsert([_embed(chunk_a), _embed(chunk_b)])

    response = RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=False,
        lexical_index=lexical,
        hybrid_alpha=1.0,
    ).execute(RetrieveRequest(query="ERR-4021", retrieval_limit=2))

    assert [hit.chunk.source_id for hit in response.hits] == ["a", "b"]
    assert response.hits[0].score == 0.9


def test_hybrid_on_prefers_lexical_when_alpha_is_one() -> None:
    chunk_a = _chunk("a", "vector favorite paraphrase")
    chunk_b = _chunk("b", "ERR-4021 exact token")
    vector = _ScriptedVectorStore(
        [
            ScoredChunk(chunk=chunk_a, score=0.9),
            ScoredChunk(chunk=chunk_b, score=0.2),
        ]
    )
    lexical = InMemoryLexicalIndex()
    lexical.upsert([_embed(chunk_a), _embed(chunk_b)])

    response = RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=1.0,
    ).execute(RetrieveRequest(query="ERR-4021", retrieval_limit=2))

    assert response.hits[0].chunk.source_id == "b"
    assert 0.0 <= response.hits[0].score <= 1.0


def test_hybrid_on_prefers_vector_when_alpha_is_zero() -> None:
    chunk_a = _chunk("a", "vector favorite paraphrase")
    chunk_b = _chunk("b", "ERR-4021 exact token")
    vector = _ScriptedVectorStore(
        [
            ScoredChunk(chunk=chunk_a, score=0.9),
            ScoredChunk(chunk=chunk_b, score=0.2),
        ]
    )
    lexical = InMemoryLexicalIndex()
    lexical.upsert([_embed(chunk_a), _embed(chunk_b)])

    response = RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=0.0,
    ).execute(RetrieveRequest(query="ERR-4021", retrieval_limit=2))

    assert response.hits[0].chunk.source_id == "a"


def test_hybrid_empty_stores_return_empty_hits() -> None:
    response = RetrieveKnowledge(
        StubEmbeddingModel(),
        InMemoryVectorStore(),
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=InMemoryLexicalIndex(),
        hybrid_alpha=0.5,
    ).execute(RetrieveRequest(query="anything", retrieval_limit=5))

    assert response.hits == ()


def test_hybrid_passes_filters_to_vector_and_lexical() -> None:
    chunk = _chunk("run", "restart steps", extra={"doc_type": "runbook"})
    vector = _ScriptedVectorStore([ScoredChunk(chunk=chunk, score=0.8)])
    lexical = _RecordingLexicalIndex()
    lexical.upsert([_embed(chunk)])
    filters = {"doc_type": "runbook"}

    RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=0.5,
    ).execute(
        RetrieveRequest(
            query="restart",
            retrieval_limit=1,
            metadata_filters=filters,
        )
    )

    assert vector.searches[0][2] == filters
    assert lexical.searches[0][2] == filters


def test_hybrid_fetches_twice_the_limit_from_each_side() -> None:
    vector = _ScriptedVectorStore(())
    lexical = _RecordingLexicalIndex()

    RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=0.5,
    ).execute(RetrieveRequest(query="q", retrieval_limit=3))

    assert vector.searches[0][1] == 6
    assert lexical.searches[0][1] == 6


def test_hybrid_enabled_without_lexical_index_is_rejected() -> None:
    with pytest.raises(ValueError, match="lexical_index"):
        RetrieveKnowledge(
            StubEmbeddingModel(),
            InMemoryVectorStore(),
            max_input_length=10_000,
            hybrid_enabled=True,
            lexical_index=None,
        )
