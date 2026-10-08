"""Typed Xray failures with fixed, secret-free messages.

Vendor response bodies, credentials, and custom field ids never reach a
message or the ``__cause__`` diagnostic.
"""

from __future__ import annotations

from types import ModuleType

from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorNetworkError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    ConnectorUnavailableError,
)

MSG_AUTH = "Xray rejected the connector credentials or permissions."
MSG_RATE_LIMIT = "Xray rate limit was exceeded."
MSG_TIMEOUT = "The Xray request timed out."
MSG_NETWORK = "The Xray network request failed."
MSG_UNAVAILABLE = "Xray is temporarily unavailable."
MSG_REQUEST_FAILED = "The Xray request failed."
MSG_REJECTED = "Xray rejected the test."
MSG_SCHEMA = "The Xray project is not configured to create tests."


class XrayRejectedError(ConnectorError):
    """Xray answered and refused one create; nothing was created for it."""

    def __init__(self) -> None:
        super().__init__(MSG_REJECTED)


class XraySchemaError(ConnectorError):
    """Required Xray create metadata is missing for the project."""

    def __init__(self) -> None:
        super().__init__(MSG_SCHEMA)


class XrayHttpDiagnostic(RuntimeError):
    """Body-free record of the raw upstream failure, kept on ``__cause__``."""


def map_http_error(error: BaseException, httpx_module: ModuleType) -> ConnectorError:
    response = getattr(error, "response", None)
    if isinstance(error, httpx_module.HTTPStatusError) and response is not None:
        status = int(response.status_code)
        if status in {401, 403}:
            return ConnectorAuthError(MSG_AUTH)
        if status == 429:
            return ConnectorRateLimitError(MSG_RATE_LIMIT)
        if status >= 500:
            return ConnectorUnavailableError(MSG_UNAVAILABLE)
        if status == 400:
            return XrayRejectedError()
        return ConnectorError(MSG_REQUEST_FAILED)
    if isinstance(error, httpx_module.TimeoutException):
        return ConnectorTimeoutError(MSG_TIMEOUT)
    if isinstance(error, httpx_module.RequestError):
        return ConnectorNetworkError(MSG_NETWORK)
    if isinstance(error, ConnectorError):
        return error
    return ConnectorError(MSG_REQUEST_FAILED)


def diagnostic(error: BaseException, httpx_module: ModuleType) -> XrayHttpDiagnostic:
    response = getattr(error, "response", None)
    if isinstance(error, httpx_module.HTTPStatusError) and response is not None:
        return XrayHttpDiagnostic(f"HTTP {response.status_code}")
    return XrayHttpDiagnostic(type(error).__name__)
