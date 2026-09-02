"""Retrieve ranked knowledge chunks through embedding and vector-store ports."""

from collections.abc import Sequence

from application.contracts import RetrieveRequest, RetrieveResponse
from application.errors import ApplicationValidationError
from application.hybrid_fusion import fuse_hybrid_scores, normalize_scores
from domain.knowledge import ScoredChunk
from domain.ports import EmbeddingModel, LexicalIndex, VectorStore

_HYBRID_CANDIDATE_MULTIPLIER = 2


def _chunk_key(chunk: ScoredChunk) -> tuple[str, str, int]:
    reference = chunk.chunk.reference
    return (str(reference.source_type), reference.source_id, chunk.chunk.index)


def _candidate_limit(retrieval_limit: int) -> int:
    return max(retrieval_limit, retrieval_limit * _HYBRID_CANDIDATE_MULTIPLIER)


def _normalized_hits(hits: Sequence[ScoredChunk]) -> tuple[ScoredChunk, ...]:
    if not hits:
        return ()
    norms = normalize_scores([float(hit.score) for hit in hits])
    ranked = sorted(
        (
            (_chunk_key(hit), ScoredChunk(chunk=hit.chunk, score=score))
            for hit, score in zip(hits, norms, strict=True)
        ),
        key=lambda pair: (-pair[1].score, pair[0]),
    )
    return tuple(hit for _, hit in ranked)


class RetrieveKnowledge:
    """Embeds a query and searches the vector store with optional metadata filters.

    Accepts ports only: the application layer must not import `infrastructure`.
    Embedding and store failures propagate as ``ProviderError`` /
    ``VectorStoreError`` — retrieval is read-only and does not wrap them in a
    typed failure carrying mutation state.

    ``execute`` is the only public retrieval entry and always enforces
    ``max_input_length`` before retrieval work, including for rewritten queries
    constructed by ``RewriteAndRetrieveKnowledge``.

    When ``hybrid_enabled`` is true, ``hybrid_alpha`` weights BM25
    (``1`` = BM25 only, ``0`` = vector only). Endpoint alphas invoke only the
    active channel. Intermediate alphas fuse both. Hybrid hit scores are in
    ``[0, 1]``, not raw cosine.

    ``vector_score_floor`` is a raw cosine eligibility floor applied only when
    Hybrid mode has an active vector channel, before normalization/fusion.
    """

    def __init__(
        self,
        embedding_model: EmbeddingModel | None,
        vector_store: VectorStore | None,
        *,
        max_input_length: int,
        hybrid_enabled: bool = False,
        lexical_index: LexicalIndex | None = None,
        hybrid_alpha: float = 0.5,
        vector_score_floor: float | None = None,
    ) -> None:
        if not isinstance(hybrid_alpha, (int, float)) or isinstance(
            hybrid_alpha, bool
        ):
            raise ValueError(
                f"hybrid_alpha must be a number in [0, 1], got {hybrid_alpha!r}"
            )
        if hybrid_alpha < 0 or hybrid_alpha > 1:
            raise ValueError(
                f"hybrid_alpha must be in [0, 1], got {hybrid_alpha!r}"
            )
        if vector_score_floor is not None and (
            not isinstance(vector_score_floor, (int, float))
            or isinstance(vector_score_floor, bool)
        ):
            raise ValueError(
                "vector_score_floor must be a number or None, "
                f"got {vector_score_floor!r}"
            )
        alpha = float(hybrid_alpha)
        needs_vector = (not hybrid_enabled) or alpha < 1.0
        needs_lexical = hybrid_enabled and alpha > 0.0
        if needs_vector and embedding_model is None:
            raise ValueError(
                "embedding_model is required when hybrid is disabled "
                "or hybrid_alpha is less than 1"
            )
        if needs_vector and vector_store is None:
            raise ValueError(
                "vector_store is required when hybrid is disabled "
                "or hybrid_alpha is less than 1"
            )
        if needs_lexical and lexical_index is None:
            raise ValueError(
                "lexical_index is required when hybrid_enabled is true "
                "and hybrid_alpha is greater than 0"
            )
        self._embedding_model = embedding_model
        self._vector_store = vector_store
        self._max_input_length = max_input_length
        self._hybrid_enabled = hybrid_enabled
        self._lexical_index = lexical_index
        self._hybrid_alpha = alpha
        self._vector_score_floor = (
            None if vector_score_floor is None else float(vector_score_floor)
        )

    def execute(self, request: RetrieveRequest) -> RetrieveResponse:
        """Return ranked chunks for ``request.query``, optionally metadata-filtered.

        Args:
            request: Validated retrieve contract (query, limit, optional filters).

        Returns:
            Ranked `ScoredChunk` hits with complete provenance and metadata.

        Raises:
            ApplicationValidationError: ``query`` exceeds ``max_input_length``.
            ProviderError: Propagated from the embedding model.
            VectorStoreError: Propagated from the vector store.
        """
        if len(request.query) > self._max_input_length:
            raise ApplicationValidationError(
                f"query must be at most {self._max_input_length} characters, "
                f"got {len(request.query)}"
            )
        if not self._hybrid_enabled:
            return RetrieveResponse(hits=self._vector_search(request))
        if self._hybrid_alpha == 0.0:
            return RetrieveResponse(
                hits=_normalized_hits(
                    self._eligible_vector_hits(self._vector_search(request))
                )
            )
        if self._hybrid_alpha == 1.0:
            return RetrieveResponse(
                hits=_normalized_hits(
                    self._lexical_search(request, limit=request.retrieval_limit)
                )
            )
        return RetrieveResponse(hits=self._fuse_search(request))

    def _eligible_vector_hits(
        self, hits: Sequence[ScoredChunk]
    ) -> tuple[ScoredChunk, ...]:
        floor = self._vector_score_floor
        if floor is None:
            return tuple(hits)
        return tuple(hit for hit in hits if hit.score >= floor)

    def _vector_search(
        self, request: RetrieveRequest, *, limit: int | None = None
    ) -> tuple[ScoredChunk, ...]:
        assert self._embedding_model is not None
        assert self._vector_store is not None
        vector = self._embedding_model.embed_query(request.query)
        return tuple(
            self._vector_store.search(
                vector,
                request.retrieval_limit if limit is None else limit,
                metadata_filters=request.metadata_filters,
            )
        )

    def _lexical_search(
        self, request: RetrieveRequest, *, limit: int | None = None
    ) -> tuple[ScoredChunk, ...]:
        assert self._lexical_index is not None
        return tuple(
            self._lexical_index.search(
                request.query,
                request.retrieval_limit if limit is None else limit,
                metadata_filters=request.metadata_filters,
            )
        )

    def _fuse_search(self, request: RetrieveRequest) -> tuple[ScoredChunk, ...]:
        assert self._lexical_index is not None
        assert self._embedding_model is not None
        assert self._vector_store is not None
        candidate_limit = _candidate_limit(request.retrieval_limit)
        vector_hits = self._eligible_vector_hits(
            self._vector_search(request, limit=candidate_limit)
        )
        lexical_hits = self._lexical_search(request, limit=candidate_limit)
        chunks: dict[tuple[str, str, int], ScoredChunk] = {}
        vector_scores: dict[tuple[str, str, int], float] = {}
        bm25_scores: dict[tuple[str, str, int], float] = {}
        for hit in vector_hits:
            key = _chunk_key(hit)
            chunks[key] = hit
            vector_scores[key] = float(hit.score)
        for hit in lexical_hits:
            key = _chunk_key(hit)
            chunks[key] = hit
            bm25_scores[key] = float(hit.score)
        if not chunks:
            return ()
        keys = list(chunks.keys())
        fused = fuse_hybrid_scores(
            bm25_scores=[bm25_scores.get(key) for key in keys],
            vector_scores=[vector_scores.get(key) for key in keys],
            alpha=self._hybrid_alpha,
        )
        ranked = sorted(
            zip(keys, fused, strict=True),
            key=lambda pair: (-pair[1], pair[0]),
        )
        limit = request.retrieval_limit
        return tuple(
            ScoredChunk(chunk=chunks[key].chunk, score=score)
            for key, score in ranked[:limit]
        )
