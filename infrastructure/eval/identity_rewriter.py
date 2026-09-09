"""Identity QueryRewriter for the offline eval harness."""

from __future__ import annotations


class IdentityQueryRewriter:
    """Returns the query unchanged.

    Used only by eval composition so ask and retrieve see the same string.
    """

    def rewrite(self, query: str) -> str:
        """Return ``query`` without calling a provider.

        Args:
            query (str): Original retrieval query.

        Returns:
            str: The same query string.
        """
        return query
