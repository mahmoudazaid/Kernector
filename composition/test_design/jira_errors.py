"""Provider-neutral failures shared by the Jira Test Design sources.

Messages are fixed so Jira diagnostics (response bodies, URLs, site names)
never reach responses or logged tracebacks.
"""

from __future__ import annotations

from application.errors import SourceReauthorizationRequiredError
from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorNetworkError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    ConnectorUnavailableError,
)

INVALID_LOCATOR = "source_locator.locator must be a Jira issue key or browse URL"
INVALID_REQUEST = "The test-design request was invalid."
NO_EVIDENCE = "No usable grounded evidence for test coverage planning."
NOT_FOUND = "The source item was not found."
NOT_CONNECTED = "The source is not connected."
REJECTED = "The source authorization was rejected. Connect again."
REQUEST_FAILED = "The source request failed."
_TRANSPORT_ERRORS: tuple[tuple[type[ConnectorError], str], ...] = (
    (ConnectorRateLimitError, "The source rate limit was exceeded."),
    (ConnectorTimeoutError, "The source request timed out."),
    (ConnectorNetworkError, "The source network request failed."),
    (ConnectorUnavailableError, "The source is temporarily unavailable."),
)


def neutral_connector_error(error: ConnectorError) -> Exception:
    """Return a fresh provider-neutral error of the same transport category."""
    if isinstance(error, ConnectorAuthError):
        return SourceReauthorizationRequiredError(REJECTED)
    for error_type, message in _TRANSPORT_ERRORS:
        if isinstance(error, error_type):
            return error_type(message)
    return ConnectorError(REQUEST_FAILED)
