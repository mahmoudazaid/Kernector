"""Retrieve ranked knowledge chunks through embedding and vector-store ports."""

from application.contracts import RetrieveRequest, RetrieveResponse
from application.errors import ApplicationValidationError
from domain.ports import EmbeddingModel, VectorStore


class RetrieveKnowledge:
    """Embeds a query and searches the vector store with optional metadata filters.

    Accepts ports only: the application layer must not import `infrastructure`.
    Embedding and store failures propagate unchanged — retrieval is read-only and
    does not wrap them in a typed failure carrying mutation state.

    ``max_input_length`` bounds caller-supplied queries on the public
    ``execute`` path. ``RewriteAndRetrieveKnowledge`` passes
    ``enforce_length=False`` for rewriter output so LLM-expanded text is not
    measured against the user-input limit after a rewrite call has already run.
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

    def execute(
        self,
        request: RetrieveRequest,
        *,
        enforce_length: bool = True,
    ) -> RetrieveResponse:
        """Return ranked chunks for `request.query`, optionally metadata-filtered.

        Args:
            request: Validated retrieve contract (query, limit, optional filters).
            enforce_length: When true (default), reject oversized ``query`` before
                embedding. Set false only for post-rewrite retrieval.

        Returns:
            Ranked `ScoredChunk` hits with complete provenance and metadata.

        Raises:
            ApplicationValidationError: ``query`` exceeds ``max_input_length``
                when ``enforce_length`` is true.
            RuntimeError: Propagated from the embedding model or vector store.
        """
        if enforce_length and len(request.query) > self._max_input_length:
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
