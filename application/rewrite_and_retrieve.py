"""Rewrite a knowledge query, then retrieve ranked chunks."""

from application.contracts import RetrieveRequest, RewriteRetrieveResponse
from application.retrieve_knowledge import RetrieveKnowledge
from domain.errors import QueryRewriterError
from domain.ports import QueryRewriter


class QueryRewriteFailure(RuntimeError):
    """Query rewrite failed before retrieval could run.

    Raised when the ``QueryRewriter`` port raises ``QueryRewriterError``, or
    when a nonconforming implementation returns blank content. The adapter is
    the primary blank detector; the use-case check is a defensive guard because
    a ``Protocol`` is structural and doubles may skip the adapter's guard.

    Unlike ``RetrieveKnowledge``, which propagates embedding and store errors
    unchanged, this use case wraps rewrite failures so callers see one typed
    application error for the rewrite step.
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
    """Rewrites the query, then delegates to ``RetrieveKnowledge``.

    Accepts ports and the retrieve use case only: the application layer must
    not import ``infrastructure``. ``RetrieveKnowledge`` stays rewrite-unaware.
    """

    def __init__(
        self,
        query_rewriter: QueryRewriter,
        retrieve: RetrieveKnowledge,
    ) -> None:
        self._query_rewriter = query_rewriter
        self._retrieve = retrieve

    def execute(self, request: RetrieveRequest) -> RewriteRetrieveResponse:
        """Rewrite ``request.query``, retrieve with the rewritten string.

        Args:
            request: Validated retrieve contract (query, limit, optional filters).

        Returns:
            Hits plus original and rewritten query strings for observability.

        Raises:
            QueryRewriteFailure: The rewriter raised ``QueryRewriterError`` or
                returned blank content. Retrieve is not invoked.
            RuntimeError: Propagated unchanged from embedding or vector store.
        """
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
        return RewriteRetrieveResponse(
            hits=retrieve_response.hits,
            original_query=request.query,
            rewritten_query=rewritten,
        )
