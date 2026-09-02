"""Retrieve ranked knowledge chunks through embedding and vector-store ports."""

from application.contracts import RetrieveRequest, RetrieveResponse
from application.errors import ApplicationValidationError
from application.hybrid_fusion import fuse_hybrid_scores
from domain.knowledge import ScoredChunk
from domain.ports import EmbeddingModel, LexicalIndex, VectorStore

_HYBRID_CANDIDATE_MULTIPLIER = 2


def _chunk_key(chunk: ScoredChunk) -> tuple[str, str, int]:
    reference = chunk.chunk.reference
    return (str(reference.source_type), reference.source_id, chunk.chunk.index)


class RetrieveKnowledge:
    """Embeds a query and searches the vector store with optional metadata filters.

    Accepts ports only: the application layer must not import `infrastructure`.
    Embedding and store failures propagate as ``ProviderError`` /
    ``VectorStoreError`` — retrieval is read-only and does not wrap them in a
    typed failure carrying mutation state.

    ``execute`` is the only public retrieval entry and always enforces
    ``max_input_length`` before ``embed_query``, including for rewritten queries
    constructed by ``RewriteAndRetrieveKnowledge``.

    When ``hybrid_enabled`` is true, lexical (BM25) and vector scores are fused
    with ``hybrid_alpha`` weighting BM25 (``1`` = BM25 only, ``0`` = vector only).
    Hybrid hit scores are fused values in ``[0, 1]``, not raw cosine.
    """

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        vector_store: VectorStore,
        *,
        max_input_length: int,
        hybrid_enabled: bool = False,
        lexical_index: LexicalIndex | None = None,
        hybrid_alpha: float = 0.5,
    ) -> None:
        if hybrid_enabled and lexical_index is None:
            raise ValueError(
                "lexical_index is required when hybrid_enabled is true"
            )
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
        self._embedding_model = embedding_model
        self._vector_store = vector_store
        self._max_input_length = max_input_length
        self._hybrid_enabled = hybrid_enabled
        self._lexical_index = lexical_index
        self._hybrid_alpha = float(hybrid_alpha)

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
        vector = self._embedding_model.embed_query(request.query)
        if not self._hybrid_enabled:
            hits = self._vector_store.search(
                vector,
                request.retrieval_limit,
                metadata_filters=request.metadata_filters,
            )
            return RetrieveResponse(hits=hits)
        return RetrieveResponse(
            hits=self._hybrid_search(request, vector)
        )

    def _hybrid_search(
        self, request: RetrieveRequest, vector: object
    ) -> tuple[ScoredChunk, ...]:
        assert self._lexical_index is not None
        candidate_limit = max(
            request.retrieval_limit,
            request.retrieval_limit * _HYBRID_CANDIDATE_MULTIPLIER,
        )
        vector_hits = self._vector_store.search(
            vector,  # type: ignore[arg-type]
            candidate_limit,
            metadata_filters=request.metadata_filters,
        )
        lexical_hits = self._lexical_index.search(
            request.query,
            candidate_limit,
            metadata_filters=request.metadata_filters,
        )
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
            bm25_scores=[bm25_scores.get(key, 0.0) for key in keys],
            vector_scores=[vector_scores.get(key, 0.0) for key in keys],
            alpha=self._hybrid_alpha,
        )
        ranked = sorted(
            zip(keys, fused, strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )
        limit = request.retrieval_limit
        return tuple(
            ScoredChunk(chunk=chunks[key].chunk, score=score)
            for key, score in ranked[:limit]
        )
