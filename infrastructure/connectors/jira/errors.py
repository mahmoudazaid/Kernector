"""Typed Jira connector failures with fixed, secret-free messages."""

from __future__ import annotations

from domain.errors import ConnectorRateLimitError, ConnectorUnavailableError

MSG_RATE_LIMIT = "Jira rate limit was exceeded."
MSG_ISSUE_LIMIT = "The selected Jira projects exceed the configured issue limit."
MSG_PAGINATION = "The Jira listing returned an inconsistent page sequence."


class JiraRateLimitError(ConnectorRateLimitError):
    """HTTP 429 from Jira; ``Retry-After`` is exposed, never retried in-adapter."""

    def __init__(self, retry_after_seconds: int | None = None) -> None:
        super().__init__(MSG_RATE_LIMIT)
        self.retry_after_seconds = retry_after_seconds


class JiraIssueLimitExceededError(ConnectorUnavailableError):
    """Listing would exceed ``JIRA_MAX_ISSUES``; the run aborts before writes."""

    def __init__(self) -> None:
        super().__init__(MSG_ISSUE_LIMIT)


class JiraPaginationError(ConnectorUnavailableError):
    """Jira returned a looping, malformed, or unbounded page sequence."""

    def __init__(self) -> None:
        super().__init__(MSG_PAGINATION)
