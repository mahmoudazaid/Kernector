"""Safe structured logging and per-turn request correlation.

Emits key=value operation records for operators. Never writes document text,
prompts, secrets, raw provider bodies, or exception message strings — only
allowlisted fields and exception *type names*.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
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


def bind_request_id(request_id: str | None = None) -> str:
    """Bind a request/operation id for the current context and return it.

    Args:
        request_id: Explicit id to reuse, or ``None`` to mint a UUID4 hex.

    Returns:
        The bound request id.
    """
    bound = request_id if request_id is not None else uuid.uuid4().hex
    _REQUEST_ID.set(bound)
    return bound


def clear_request_id() -> None:
    """Clear the bound request id for the current context."""
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
    """Emit one structured operation record with allowlisted fields only.

    Always includes ``operation`` and ``outcome``. Includes ``request_id`` when
    one is bound via :func:`bind_request_id`. Forbidden or unknown keyword
    arguments are dropped so callers cannot accidentally log content.

    Args:
        logger: Destination logger (typically ``logging.getLogger(__name__)``).
        operation: Use-case or composition operation name (e.g. ``ask``).
        outcome: Result label (e.g. ``success``, ``error``, ``insufficient``).
        level: Stdlib logging level; defaults to ``INFO``.
        **fields: Candidate structured fields; only the allowlist is emitted.
    """
    parts = [f"operation={operation}", f"outcome={outcome}"]
    request_id = current_request_id()
    if request_id is not None:
        parts.append(f"request_id={request_id}")
    for key in sorted(fields):
        if key in _FORBIDDEN_FIELDS or key not in _ALLOWED_FIELDS:
            continue
        value = fields[key]
        if value is None:
            continue
        parts.append(f"{key}={value}")
    logger.log(level, " ".join(parts))
