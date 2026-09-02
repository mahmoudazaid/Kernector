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


def test_hybrid_enabled_without_lexical_index_is_rejected_when_alpha_positive() -> None:
    with pytest.raises(ValueError, match="lexical_index"):
        RetrieveKnowledge(
            StubEmbeddingModel(),
            InMemoryVectorStore(),
            max_input_length=10_000,
            hybrid_enabled=True,
            lexical_index=None,
            hybrid_alpha=0.5,
        )


def test_hybrid_alpha_zero_allows_missing_lexical_index() -> None:
    RetrieveKnowledge(
        StubEmbeddingModel(),
        InMemoryVectorStore(),
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=None,
        hybrid_alpha=0.0,
    )


def test_hybrid_alpha_one_allows_missing_embedding() -> None:
    lexical = InMemoryLexicalIndex()
    RetrieveKnowledge(
        None,
        None,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=1.0,
    )


def test_hybrid_lexical_only_candidate_not_inflated_by_negative_vector_peers() -> None:
    """Disjoint channels: missing vector score must not become raw 0.0 before norm."""
    lexical_only = _chunk("lex", "ERR-4021 unique-token")
    lexical_weak = _chunk("lex-weak", "other lexical filler")
    vector_low = _chunk("vlow", "unrelated paraphrase low")
    vector_high = _chunk("vhigh", "unrelated paraphrase high")
    vector = _ScriptedVectorStore(
        [
            ScoredChunk(chunk=vector_low, score=-0.8),
            ScoredChunk(chunk=vector_high, score=0.8),
        ]
    )
    lexical = InMemoryLexicalIndex()
    lexical.upsert([_embed(lexical_only), _embed(lexical_weak)])

    response = RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=0.5,
    ).execute(RetrieveRequest(query="ERR-4021 unique-token", retrieval_limit=4))

    by_id = {hit.chunk.source_id: hit.score for hit in response.hits}
    assert by_id["lex"] == pytest.approx(0.5)
    assert by_id["lex"] < 0.75


def test_hybrid_tie_break_is_deterministic_by_chunk_identity() -> None:
    chunk_a = _chunk("a", "shared token alpha")
    chunk_b = _chunk("b", "shared token beta")
    vector = _ScriptedVectorStore(
        [
            ScoredChunk(chunk=chunk_b, score=0.5),
            ScoredChunk(chunk=chunk_a, score=0.5),
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
    ).execute(RetrieveRequest(query="shared token", retrieval_limit=2))

    assert [hit.chunk.source_id for hit in response.hits] == ["a", "b"]
    assert response.hits[0].score == response.hits[1].score


def test_hybrid_single_vector_hit_score_is_one_and_clears_positive_threshold() -> None:
    chunk = _chunk("only", "semantic paraphrase about outages")
    vector = _ScriptedVectorStore([ScoredChunk(chunk=chunk, score=0.31)])
    lexical = InMemoryLexicalIndex()

    response = RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=0.0,
    ).execute(RetrieveRequest(query="unrelated query terms xyz", retrieval_limit=3))

    assert len(response.hits) == 1
    assert response.hits[0].chunk.source_id == "only"
    assert response.hits[0].score == pytest.approx(1.0)
    assert response.hits[0].score >= 0.25


def test_hybrid_without_lexical_overlap_keeps_only_vector_candidates() -> None:
    from infrastructure.lexical.bm25 import Bm25LexicalIndex

    vector_hit = _chunk("vec", "semantic paraphrase about payment outages")
    noise = _chunk("noise", "blue-green deploy rollout capacity notes")
    vector = _ScriptedVectorStore([ScoredChunk(chunk=vector_hit, score=0.88)])
    lexical = Bm25LexicalIndex()
    lexical.upsert([_embed(noise), _embed(_chunk("filler-a", "alpha")), _embed(_chunk("filler-b", "beta"))])

    response = RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=0.5,
    ).execute(
        RetrieveRequest(query="zzzz-not-in-corpus-qqqq", retrieval_limit=5)
    )

    assert [hit.chunk.source_id for hit in response.hits] == ["vec"]
    assert response.hits[0].score == pytest.approx(0.5)


class _RaisingLexicalIndex:
    def upsert(self, embedded: Sequence[EmbeddedChunk]) -> None:
        return None

    def search(self, query: str, limit: int, *, metadata_filters=None):  # type: ignore[no-untyped-def]
        raise AssertionError("lexical search must not run at hybrid_alpha=0")

    def delete_source(self, reference: SourceReference) -> None:
        return None


class _RaisingEmbedding:
    def embed_documents(self, texts: Sequence[str]) -> Sequence[Vector]:
        raise AssertionError("embed_documents must not run")

    def embed_query(self, text: str) -> Vector:
        raise AssertionError("embed_query must not run at hybrid_alpha=1")


class _RaisingVectorStore:
    def upsert(self, embedded: Sequence[EmbeddedChunk]) -> None:
        return None

    def search(self, vector, limit, *, metadata_filters=None):  # type: ignore[no-untyped-def]
        raise AssertionError("vector search must not run at hybrid_alpha=1")

    def delete_source(self, reference: SourceReference) -> None:
        return None


def test_hybrid_alpha_zero_never_invokes_lexical_and_excludes_lexical_only() -> None:
    vector_hit = _chunk("vec", "semantic paraphrase")
    vector = _ScriptedVectorStore([ScoredChunk(chunk=vector_hit, score=0.7)])

    response = RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=_RaisingLexicalIndex(),
        hybrid_alpha=0.0,
    ).execute(RetrieveRequest(query="ERR-4021", retrieval_limit=5))

    assert [hit.chunk.source_id for hit in response.hits] == ["vec"]
    assert all(hit.score >= 0.0 for hit in response.hits)
    assert "lex" not in {hit.chunk.source_id for hit in response.hits}


class _VectorOnlyIfCalledStore:
    """Would return a vector-only hit if search were invoked (must stay unused)."""

    def __init__(self, hit: ScoredChunk) -> None:
        self._hit = hit
        self.search_calls = 0

    def upsert(self, embedded: Sequence[EmbeddedChunk]) -> None:
        return None

    def search(self, vector, limit, *, metadata_filters=None):  # type: ignore[no-untyped-def]
        self.search_calls += 1
        return (self._hit,)

    def delete_source(self, reference: SourceReference) -> None:
        return None


def test_hybrid_alpha_one_never_invokes_embedding_or_vector_search() -> None:
    lexical_only = _chunk("lex", "ERR-4021 recovery steps")
    vector_only = _chunk("vec", "semantic paraphrase without shared tokens")
    lexical = InMemoryLexicalIndex()
    lexical.upsert([_embed(lexical_only)])
    vector = _VectorOnlyIfCalledStore(ScoredChunk(chunk=vector_only, score=0.99))

    response = RetrieveKnowledge(
        _RaisingEmbedding(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=1.0,
    ).execute(RetrieveRequest(query="ERR-4021", retrieval_limit=5))

    assert vector.search_calls == 0
    assert [hit.chunk.source_id for hit in response.hits] == ["lex"]
    assert "vec" not in {hit.chunk.source_id for hit in response.hits}


def test_hybrid_alpha_one_empty_lexical_returns_empty() -> None:
    response = RetrieveKnowledge(
        None,
        None,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=InMemoryLexicalIndex(),
        hybrid_alpha=1.0,
    ).execute(RetrieveRequest(query="anything", retrieval_limit=3))

    assert response.hits == ()


def test_hybrid_alpha_zero_passes_filters_to_vector_only() -> None:
    chunk = _chunk("run", "restart steps", extra={"doc_type": "runbook"})
    vector = _ScriptedVectorStore([ScoredChunk(chunk=chunk, score=0.8)])
    filters = {"doc_type": "runbook"}

    RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=_RaisingLexicalIndex(),
        hybrid_alpha=0.0,
    ).execute(
        RetrieveRequest(query="restart", retrieval_limit=1, metadata_filters=filters)
    )

    assert vector.searches[0][2] == filters


def test_hybrid_alpha_one_passes_filters_to_lexical_only() -> None:
    chunk = _chunk("run", "restart steps", extra={"doc_type": "runbook"})
    lexical = _RecordingLexicalIndex()
    lexical.upsert([_embed(chunk)])
    filters = {"doc_type": "runbook"}

    RetrieveKnowledge(
        None,
        None,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=1.0,
    ).execute(
        RetrieveRequest(query="restart", retrieval_limit=1, metadata_filters=filters)
    )

    assert lexical.searches[0][2] == filters


def test_hybrid_intermediate_alpha_still_invokes_both_channels() -> None:
    chunk = _chunk("both", "restart ERR-4021 steps")
    vector = _ScriptedVectorStore([ScoredChunk(chunk=chunk, score=0.8)])
    lexical = _RecordingLexicalIndex()
    lexical.upsert([_embed(chunk)])

    RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=0.5,
    ).execute(RetrieveRequest(query="ERR-4021", retrieval_limit=1))

    assert len(vector.searches) == 1
    assert len(lexical.searches) == 1


def test_hybrid_alpha_zero_rejects_all_negative_raw_vector_scores() -> None:
    vector = _ScriptedVectorStore(
        [
            ScoredChunk(chunk=_chunk("bad-a", "unrelated a"), score=-0.9),
            ScoredChunk(chunk=_chunk("bad-b", "unrelated b"), score=-0.8),
        ]
    )

    response = RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        hybrid_alpha=0.0,
        vector_score_floor=0.0,
    ).execute(RetrieveRequest(query="anything", retrieval_limit=5))

    assert response.hits == ()


def test_hybrid_intermediate_negative_vectors_without_lexical_overlap_return_empty() -> None:
    from infrastructure.lexical.bm25 import Bm25LexicalIndex

    vector = _ScriptedVectorStore(
        [
            ScoredChunk(chunk=_chunk("bad-a", "unrelated a"), score=-0.9),
            ScoredChunk(chunk=_chunk("bad-b", "unrelated b"), score=-0.8),
        ]
    )
    lexical = Bm25LexicalIndex()
    lexical.upsert(
        [
            _embed(_chunk("noise", "blue-green deploy notes")),
            _embed(_chunk("filler", "capacity planning")),
        ]
    )

    response = RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=0.5,
        vector_score_floor=0.0,
    ).execute(RetrieveRequest(query="zzzz-not-in-corpus-qqqq", retrieval_limit=5))

    assert response.hits == ()


def test_hybrid_vector_floor_keeps_only_eligible_before_normalization() -> None:
    below = _chunk("below", "dissimilar below floor")
    low = _chunk("low", "weak but eligible")
    high = _chunk("high", "stronger eligible")
    vector = _ScriptedVectorStore(
        [
            ScoredChunk(chunk=below, score=-0.5),
            ScoredChunk(chunk=low, score=0.2),
            ScoredChunk(chunk=high, score=0.4),
        ]
    )

    response = RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        hybrid_alpha=0.0,
        vector_score_floor=0.0,
    ).execute(RetrieveRequest(query="topic", retrieval_limit=5))

    assert [hit.chunk.source_id for hit in response.hits] == ["high", "low"]
    assert response.hits[0].score == pytest.approx(1.0)
    assert response.hits[1].score == pytest.approx(0.0)
    assert "below" not in {hit.chunk.source_id for hit in response.hits}


def test_hybrid_rejected_vector_candidates_do_not_affect_surviving_normalization() -> None:
    """If -0.5 entered min-max with 0.2/0.4, low would not normalize to 0.0."""
    vector = _ScriptedVectorStore(
        [
            ScoredChunk(chunk=_chunk("below", "noise"), score=-0.5),
            ScoredChunk(chunk=_chunk("low", "eligible low"), score=0.2),
            ScoredChunk(chunk=_chunk("high", "eligible high"), score=0.4),
        ]
    )

    response = RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        hybrid_alpha=0.0,
        vector_score_floor=0.0,
    ).execute(RetrieveRequest(query="topic", retrieval_limit=5))

    by_id = {hit.chunk.source_id: hit.score for hit in response.hits}
    assert by_id == {"high": pytest.approx(1.0), "low": pytest.approx(0.0)}


def test_hybrid_lexical_match_survives_when_all_vector_candidates_rejected() -> None:
    lexical_hit = _chunk("lex", "ERR-4021 recovery steps")
    vector = _ScriptedVectorStore(
        [
            ScoredChunk(chunk=_chunk("bad-a", "unrelated a"), score=-0.9),
            ScoredChunk(chunk=_chunk("bad-b", "unrelated b"), score=-0.7),
        ]
    )
    lexical = InMemoryLexicalIndex()
    lexical.upsert([_embed(lexical_hit)])

    response = RetrieveKnowledge(
        StubEmbeddingModel(),
        vector,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=lexical,
        hybrid_alpha=0.5,
        vector_score_floor=0.0,
    ).execute(RetrieveRequest(query="ERR-4021", retrieval_limit=3))

    assert [hit.chunk.source_id for hit in response.hits] == ["lex"]
    assert response.hits[0].score == pytest.approx(0.5)
