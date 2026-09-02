"""Rewrite a knowledge query, then retrieve ranked chunks."""

from collections.abc import Sequence
import logging

from application.contracts import RetrieveRequest, RewriteRetrieveResponse
from application.errors import ApplicationValidationError
from application.input_safety import reject_unsafe_query
from application.observability import log_operation
from application.retrieve_knowledge import RetrieveKnowledge
from domain.errors import ProviderError, QueryRewriterError
from domain.knowledge import ScoredChunk
from domain.ports import QueryRewriter

logger = logging.getLogger(__name__)


class QueryRewriteFailure(ProviderError):
    """Query rewrite failed before retrieval could run.

    Raised when the ``QueryRewriter`` port raises ``QueryRewriterError``, or
    when a nonconforming implementation returns blank content. The adapter is
    the primary blank detector; the use-case check is a defensive guard because
    a ``Protocol`` is structural and doubles may skip the adapter's guard.

    Unlike ``RetrieveKnowledge``, which propagates embedding and store errors
    unchanged, this use case wraps rewrite failures so callers see one typed
    application error for the rewrite step. Subclasses ``ProviderError`` so
    presentation can treat rewrite failures as trusted provider messages.
    """

    def __init__(
        self,
        message: str,
        *,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.__cause__ = cause


class RewriteAndRetrieveKnowledge:
    """Rewrites the query, then delegates to ``RetrieveKnowledge.execute``.

    Accepts ports and the retrieve use case only: the application layer must
    not import ``infrastructure``.

    The original query is length-checked before the rewriter runs. The rewritten
    string is wrapped in a normal ``RetrieveRequest`` and passed to
    ``RetrieveKnowledge.execute``, which enforces the same limit again before
    embedding — so oversized rewriter output never reaches embed or store.
    """

    def __init__(
        self,
        query_rewriter: QueryRewriter,
        retrieve: RetrieveKnowledge,
        *,
        max_input_length: int,
    ) -> None:
        self._query_rewriter = query_rewriter
        self._retrieve = retrieve
        self._max_input_length = max_input_length

    def execute(self, request: RetrieveRequest) -> RewriteRetrieveResponse:
        """Rewrite ``request.query``, retrieve with the rewritten string.

        Args:
            request: Validated retrieve contract (query, limit, optional filters).

        Returns:
            Hits plus original and rewritten query strings for observability.

        Raises:
            ApplicationValidationError: Original or rewritten query exceeds
                ``max_input_length`` (rewritten case: after rewrite, before
                embed/store), or the original query fails platform
                input-safety reject rules.
            QueryRewriteFailure: The rewriter raised ``QueryRewriterError`` or
                returned blank content. Retrieve is not invoked.
            ProviderError: Propagated from the embedding provider.
            VectorStoreError: Propagated from the vector store.
        """
        try:
            return self._execute(request)
        except ApplicationValidationError:
            raise
        except Exception as error:
            log_operation(
                logger,
                operation="rewrite_retrieve",
                outcome="error",
                level=logging.ERROR,
                error_type=type(error).__name__,
            )
            raise

    def _execute(self, request: RetrieveRequest) -> RewriteRetrieveResponse:
        if len(request.query) > self._max_input_length:
            raise ApplicationValidationError(
                f"query must be at most {self._max_input_length} characters, "
                f"got {len(request.query)}"
            )
        reject_unsafe_query(request.query)
        try:
            rewritten = self._query_rewriter.rewrite(request.query)
        except QueryRewriterError as error:
            raise QueryRewriteFailure(str(error), cause=error) from error

        if not isinstance(rewritten, str) or not rewritten.strip():
            raise QueryRewriteFailure("Query rewrite returned a blank retrieval query")

        rewritten = rewritten.strip()
        retrieve_response = self._retrieve.execute(
            RetrieveRequest(
                query=rewritten,
                retrieval_limit=request.retrieval_limit,
                metadata_filters=request.metadata_filters,
            )
        )
        log_operation(
            logger,
            operation="rewrite_retrieve",
            outcome="success",
            hit_count=len(retrieve_response.hits),
            source_type=_source_types(retrieve_response.hits),
        )
        return RewriteRetrieveResponse(
            hits=retrieve_response.hits,
            original_query=request.query,
            rewritten_query=rewritten,
        )


def _source_types(hits: Sequence[ScoredChunk]) -> str | None:
    """Sorted unique source_type values from hits, or ``None`` when empty."""
    types = sorted({hit.chunk.reference.source_type for hit in hits})
    if not types:
        return None
    return ",".join(types)
