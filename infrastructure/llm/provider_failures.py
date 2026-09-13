"""Classify LLM provider transport/API failures into typed domain errors.

Adapters call :func:`classify_provider_failure` on invoke/transport failures
and raise the result with ``from error`` so vendor detail stays on
``__cause__``. Exception text is always adapter-authored; never copy vendor
bodies, headers, or secrets into the returned message.
"""

from __future__ import annotations

from collections.abc import Iterable

import requests
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)

from domain.errors import (
    ProviderAuthError,
    ProviderCreditsError,
    ProviderError,
    ProviderModelUnavailableError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

_MSG_AUTH = "The model provider rejected authentication."
_MSG_CREDITS = "The model provider has insufficient credits."
_MSG_MODEL = "The requested model is unavailable."
_MSG_RATE = "The model provider rate-limited the request."
_MSG_TIMEOUT = "The model provider timed out."
_MSG_NETWORK = "The model provider could not be reached."

_CREDIT_CODES = frozenset({
    "payment_required",
    "insufficient_quota",
    "billing_not_active",
    "insufficient_credits",
})
_MODEL_CODES = frozenset({
    "model_not_found",
    "model_unavailable",
})
_AUTH_CODES = frozenset({
    "invalid_api_key",
    "invalid_api_token",
    "authentication_error",
})


def classify_provider_failure(
    error: BaseException,
    *,
    fallback_message: str,
) -> ProviderError:
    """Map a provider failure to a typed ``ProviderError`` subclass.

    Args:
        error: The caught provider/transport exception (or chain root).
        fallback_message: Fixed message when no actionable category matches.

    Returns:
        A new ``ProviderError`` (possibly a subclass) with fixed text. Callers
        must ``raise ... from error`` to retain the vendor cause.
    """
    for exc in _exception_chain(error):
        classified = _classify_one(exc)
        if classified is not None:
            return classified
    return ProviderError(fallback_message)


def _exception_chain(error: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__


def _classify_one(exc: BaseException) -> ProviderError | None:
    if isinstance(exc, (APITimeoutError, TimeoutError, requests.exceptions.Timeout)):
        return ProviderTimeoutError(_MSG_TIMEOUT)

    if isinstance(exc, AuthenticationError):
        return ProviderAuthError(_MSG_AUTH)

    # Structured provider codes must win over RateLimitError / PermissionDeniedError
    # isinstance checks: exhausted credits arrive as 429+insufficient_quota and
    # 403+billing_not_active on those SDK types.
    code = _provider_error_code(exc)
    if code in _AUTH_CODES:
        return ProviderAuthError(_MSG_AUTH)
    if code in _CREDIT_CODES:
        return ProviderCreditsError(_MSG_CREDITS)
    if code in _MODEL_CODES:
        return ProviderModelUnavailableError(_MSG_MODEL)

    if isinstance(exc, RateLimitError):
        return ProviderRateLimitError(_MSG_RATE)

    if isinstance(exc, PermissionDeniedError):
        return ProviderAuthError(_MSG_AUTH)

    status = _http_status(exc)
    if status == 401:
        return ProviderAuthError(_MSG_AUTH)
    if status == 402:
        return ProviderCreditsError(_MSG_CREDITS)
    if status == 403:
        return ProviderAuthError(_MSG_AUTH)
    if status == 404:
        return ProviderModelUnavailableError(_MSG_MODEL)
    if status == 408:
        return ProviderTimeoutError(_MSG_TIMEOUT)
    if status == 429:
        return ProviderRateLimitError(_MSG_RATE)

    if isinstance(
        exc,
        (APIConnectionError, ConnectionError, requests.exceptions.ConnectionError),
    ):
        return ProviderNetworkError(_MSG_NETWORK)

    return None


def _http_status(exc: BaseException) -> int | None:
    raw = getattr(exc, "status_code", None)
    if raw is None:
        response = getattr(exc, "response", None)
        raw = getattr(response, "status_code", None)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _provider_error_code(exc: BaseException) -> str | None:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        nested = body.get("error")
        if isinstance(nested, dict):
            nested_code = nested.get("code")
            if isinstance(nested_code, str) and nested_code:
                return nested_code
        top_code = body.get("code")
        if isinstance(top_code, str) and top_code:
            return top_code
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    return None
