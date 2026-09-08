"""Shared pack-local validation helpers for Software Delivery tools."""

from __future__ import annotations

from typing import TypeVar

_E = TypeVar("_E", bound=Exception)


def require_nonblank_str(
    value: object, field_name: str, error: type[_E]
) -> str:
    """Require a non-blank string, reporting only the type name on mismatch."""
    if not isinstance(value, str):
        raise error(
            f"{field_name} must be a non-blank string, got {type(value).__name__}"
        )
    if not value.strip():
        raise error(f"{field_name} must be a non-blank string")
    return value
