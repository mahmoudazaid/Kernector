"""Helpers for asserting safe structured log records in tests."""

from __future__ import annotations

import json
import logging
from typing import Any


def flatten_log_record(record: logging.LogRecord) -> str:
    """Flatten a LogRecord into one searchable string (message, args, extras)."""
    parts: list[str] = [record.getMessage(), repr(record.args)]
    for key, value in record.__dict__.items():
        if key in {"msg", "args", "exc_info", "exc_text", "stack_info"}:
            continue
        parts.append(f"{key}={value!r}")
    if record.exc_info is not None:
        parts.append(repr(record.exc_info))
    return "\n".join(parts)


def operation_payload(record: logging.LogRecord) -> dict[str, Any]:
    """Parse the JSON operation payload from a structured log record."""
    payload = json.loads(record.getMessage())
    if not isinstance(payload, dict):
        raise AssertionError(f"expected JSON object payload, got {payload!r}")
    return payload


def operation_records(
    records: list[logging.LogRecord], *, operation: str
) -> list[logging.LogRecord]:
    """Return records whose JSON payload names the given operation."""
    matched: list[logging.LogRecord] = []
    for record in records:
        try:
            payload = operation_payload(record)
        except (json.JSONDecodeError, AssertionError, TypeError):
            continue
        if payload.get("operation") == operation:
            matched.append(record)
    return matched
