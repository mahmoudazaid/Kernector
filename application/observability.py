"""Safe structured logging and per-turn request correlation.

Emits one JSON object per operation for operators. Never writes document text,
prompts, secrets, raw provider bodies, or exception message strings — only
allowlisted fields and exception *type names*. String values are normalized so
newlines and control characters cannot forge extra log events.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar, Token
from typing import Any

_REQUEST_ID: ContextVar[str | None] = ContextVar("kernector_request_id", default=None)

_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "latency_ms",
        "model",
        "pack",
        "tool",
        "source_type",
        "hit_count",
        "chunk_count",
        "source_count",
        "prompt_key",
        "error_type",
        "path",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
)

_FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {
        "query",
        "content",
        "prompt",
        "arguments",
        "result",
        "message",
        "body",
        "text",
        "answer",
        "history",
        "chunks",
        "documents",
        "secret",
        "api_key",
        "token",
        "password",
    }
)

_INT_FIELDS: frozenset[str] = frozenset(
    {
        "latency_ms",
        "hit_count",
        "chunk_count",
        "source_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
)


def bind_request_id(request_id: str | None = None) -> tuple[str, Token | None]:
    """Bind a request/operation id for the current context.

    When ``request_id`` is omitted and an id is already bound, the existing id
    is reused and the returned token is ``None`` (no reset needed). Otherwise a
    new binding is installed and the caller must
    :func:`reset_request_id` with the returned token.

    Args:
        request_id: Explicit id to install, or ``None`` to reuse or mint.

    Returns:
        The effective request id and an optional ContextVar token to reset.
    """
    current = _REQUEST_ID.get()
    if request_id is None and current is not None:
        return current, None
    bound = request_id if request_id is not None else uuid.uuid4().hex
    token = _REQUEST_ID.set(bound)
    return bound, token


def reset_request_id(token: Token | None) -> None:
    """Restore the previous request id binding using a token from bind."""
    if token is not None:
        _REQUEST_ID.reset(token)


def clear_request_id() -> None:
    """Force-clear the bound request id (tests / last-resort cleanup only)."""
    _REQUEST_ID.set(None)


def current_request_id() -> str | None:
    """Return the bound request id, or ``None`` when unbound."""
    return _REQUEST_ID.get()


def log_operation(
    logger: logging.Logger,
    *,
    operation: str,
    outcome: str,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit one single-line JSON operation record with allowlisted fields only.

    Always includes ``operation`` and ``outcome``. Includes ``request_id`` when
    one is bound via :func:`bind_request_id`. Forbidden or unknown keyword
    arguments are dropped. String values (including ``operation`` and
    ``outcome``) are normalized to strip control characters so one call cannot
    forge additional log lines or alternate ``operation`` events.

    Args:
        logger: Destination logger (typically ``logging.getLogger(__name__)``).
        operation: Use-case or composition operation name (e.g. ``ask``).
        outcome: Result label (e.g. ``success``, ``error``, ``insufficient``).
        level: Stdlib logging level; defaults to ``INFO``.
        **fields: Candidate structured fields; only the allowlist is emitted.
    """
    payload: dict[str, Any] = {
        "operation": _safe_str(operation),
        "outcome": _safe_str(outcome),
    }
    request_id = current_request_id()
    if request_id is not None:
        payload["request_id"] = _safe_str(request_id)
    for key in sorted(fields):
        if key in _FORBIDDEN_FIELDS or key not in _ALLOWED_FIELDS:
            continue
        value = fields[key]
        if value is None:
            continue
        if key in _INT_FIELDS:
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            payload[key] = value
            continue
        payload[key] = _safe_str(value)
    message = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    logger.log(level, message, extra={"kernector": payload})


def _safe_str(value: object) -> str:
    """Normalize a log field to a single-line printable string."""
    text = value if isinstance(value, str) else str(value)
    return "".join(ch if ch.isprintable() and ch not in "\n\r" else "?" for ch in text)
