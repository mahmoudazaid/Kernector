"""Helpers for asserting safe structured log records in tests."""

from __future__ import annotations

import logging


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


def operation_records(
    records: list[logging.LogRecord], *, operation: str
) -> list[logging.LogRecord]:
    """Return records whose message names the given operation."""
    needle = f"operation={operation}"
    return [record for record in records if needle in record.getMessage()]
