"""Shared Google Drive HTTP/auth error mapping (sanitized public messages)."""

from __future__ import annotations

import json
from collections.abc import Mapping

from google.auth.exceptions import (
    RefreshError,
    TimeoutError as GoogleAuthTimeoutError,
    TransportError,
)
from googleapiclient.errors import HttpError
from httplib2 import HttpLib2Error

from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorUnavailableError,
)

MSG_AUTH = "Google Drive rejected the connector credentials or permissions."
MSG_UNAVAILABLE = "Google Drive is temporarily unavailable."
MSG_REQUEST_FAILED = "The Google Drive request failed."

_RATE_LIMIT_REASONS = frozenset(
    {
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "quotaExceeded",
        "dailyLimitExceeded",
        "sharingRateLimitExceeded",
    }
)


def map_google_error(error: BaseException) -> ConnectorError:
    """Map a Google SDK / transport failure to a sanitized connector error."""
    if isinstance(error, RefreshError):
        return ConnectorAuthError(MSG_AUTH)
    if isinstance(error, HttpError):
        return map_http_error(error)
    if isinstance(
        error,
        (
            TimeoutError,
            ConnectionError,
            OSError,
            HttpLib2Error,
            TransportError,
            GoogleAuthTimeoutError,
        ),
    ):
        return ConnectorUnavailableError(MSG_UNAVAILABLE)
    return ConnectorError(MSG_REQUEST_FAILED)


def map_http_error(error: HttpError) -> ConnectorError:
    """Map an ``HttpError`` status/reason set to a sanitized connector error."""
    status = _http_status(error)
    if status == 401:
        return ConnectorAuthError(MSG_AUTH)
    if status == 403:
        reasons = _http_reasons(error)
        if reasons & _RATE_LIMIT_REASONS:
            return ConnectorUnavailableError(MSG_UNAVAILABLE)
        return ConnectorAuthError(MSG_AUTH)
    if status in {408, 429} or (status is not None and status >= 500):
        return ConnectorUnavailableError(MSG_UNAVAILABLE)
    return ConnectorError(MSG_REQUEST_FAILED)


def _http_status(error: HttpError) -> int | None:
    raw = getattr(error.resp, "status", None)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _http_reasons(error: HttpError) -> set[str]:
    try:
        payload = json.loads(error.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    body = payload.get("error")
    if not isinstance(body, dict):
        return set()
    reasons: set[str] = set()
    errors = body.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, Mapping):
                reason = item.get("reason")
                if isinstance(reason, str):
                    reasons.add(reason)
    reason = body.get("reason")
    if isinstance(reason, str):
        reasons.add(reason)
    return reasons
