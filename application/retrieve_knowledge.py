"""Retrieve ranked knowledge chunks through embedding and vector-store ports."""

from collections.abc import Mapping
from dataclasses import dataclass

from application.contracts import RetrieveRequest, RetrieveResponse
from application.errors import ApplicationValidationError
from domain.ports import EmbeddingModel, VectorStore


@dataclass(frozen=True, slots=True)
class TrustedRewrittenQuery:
    """Retrieval text produced by a ``QueryRewriter`` after the caller query was bounded.

    Not an adapter-facing contract. Only ``RewriteAndRetrieveKnowledge`` constructs
    it, so ``RetrieveKnowledge.execute_rewritten`` can embed without re-applying
    the user-input length limit to model-generated text.
    """

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ApplicationValidationError("rewritten query must be non-empty")
        object.__setattr__(self, "text", self.text.strip())


class RetrieveKnowledge:
    """Embeds a query and searches the vector store with optional metadata filters.

    Accepts ports only: the application layer must not import `infrastructure`.
    Embedding and store failures propagate unchanged — retrieval is read-only and
    does not wrap them in a typed failure carrying mutation state.

    ``execute`` always enforces ``max_input_length`` on caller-supplied text.
    Rewriter output uses ``execute_rewritten`` with ``TrustedRewrittenQuery``.
    """

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        vector_store: VectorStore,
        *,
        max_input_length: int,
    ) -> None:
        self._embedding_model = embedding_model
        self._vector_store = vector_store
        self._max_input_length = max_input_length

    def execute(self, request: RetrieveRequest) -> RetrieveResponse:
        """Return ranked chunks for a caller-supplied ``request.query``.

        Args:
            request: Validated retrieve contract (query, limit, optional filters).

        Returns:
            Ranked `ScoredChunk` hits with complete provenance and metadata.

        Raises:
            ApplicationValidationError: ``query`` exceeds ``max_input_length``.
            RuntimeError: Propagated from the embedding model or vector store.
        """
        if len(request.query) > self._max_input_length:
            raise ApplicationValidationError(
                f"query must be at most {self._max_input_length} characters, "
                f"got {len(request.query)}"
            )
        return self._search(
            request.query,
            request.retrieval_limit,
            request.metadata_filters,
        )

    def execute_rewritten(
        self,
        query: TrustedRewrittenQuery,
        *,
        retrieval_limit: int,
        metadata_filters: Mapping[str, str] | None = None,
    ) -> RetrieveResponse:
        """Embed rewriter output without re-applying the user-input length limit.

        Args:
            query: Trusted rewritten text (caller already bounded the original).
            retrieval_limit: Positive cap on ranked hits.
            metadata_filters: Optional opaque exact-match AND filters.

        Returns:
            Ranked `ScoredChunk` hits with complete provenance and metadata.
        """
        if not isinstance(query, TrustedRewrittenQuery):
            raise ApplicationValidationError(
                f"query must be a TrustedRewrittenQuery, got {query!r}"
            )
        return self._search(query.text, retrieval_limit, metadata_filters)

    def _search(
        self,
        query: str,
        retrieval_limit: int,
        metadata_filters: Mapping[str, str] | None,
    ) -> RetrieveResponse:
        vector = self._embedding_model.embed_query(query)
        hits = self._vector_store.search(
            vector,
            retrieval_limit,
            metadata_filters=metadata_filters,
        )
        return RetrieveResponse(hits=hits)
