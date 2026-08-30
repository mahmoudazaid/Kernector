"""Retrieve ranked knowledge chunks through embedding and vector-store ports."""

from application.contracts import RetrieveRequest, RetrieveResponse
from application.errors import ApplicationValidationError
from domain.ports import EmbeddingModel, VectorStore


class RetrieveKnowledge:
    """Embeds a query and searches the vector store with optional metadata filters.

    Accepts ports only: the application layer must not import `infrastructure`.
    Embedding and store failures propagate unchanged — retrieval is read-only and
    does not wrap them in a typed failure carrying mutation state.

    ``execute`` is the only public retrieval entry and always enforces
    ``max_input_length`` before ``embed_query``, including for rewritten queries
    constructed by ``RewriteAndRetrieveKnowledge``.
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
        """Return ranked chunks for ``request.query``, optionally metadata-filtered.

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
        vector = self._embedding_model.embed_query(request.query)
        hits = self._vector_store.search(
            vector,
            request.retrieval_limit,
            metadata_filters=request.metadata_filters,
        )
        return RetrieveResponse(hits=hits)
