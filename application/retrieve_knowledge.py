"""Retrieve ranked knowledge chunks through embedding and vector-store ports."""

from application.contracts import RetrieveRequest, RetrieveResponse
from domain.ports import EmbeddingModel, VectorStore


class RetrieveKnowledge:
    """Embeds a query and searches the vector store with optional metadata filters.

    Accepts ports only: the application layer must not import `infrastructure`.
    Embedding and store failures propagate unchanged — retrieval is read-only and
    does not wrap them in a typed failure carrying mutation state.
    """

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        vector_store: VectorStore,
    ) -> None:
        self._embedding_model = embedding_model
        self._vector_store = vector_store

    def execute(self, request: RetrieveRequest) -> RetrieveResponse:
        """Return ranked chunks for `request.query`, optionally metadata-filtered.

        Args:
            request: Validated retrieve contract (query, limit, optional filters).

        Returns:
            Ranked `ScoredChunk` hits with complete provenance and metadata.

        Raises:
            RuntimeError: Propagated from the embedding model or vector store.
        """
        vector = self._embedding_model.embed_query(request.query)
        hits = self._vector_store.search(
            vector,
            request.retrieval_limit,
            metadata_filters=request.metadata_filters,
        )
        return RetrieveResponse(hits=hits)
