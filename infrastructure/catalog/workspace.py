"""Shared workspace_id validation for settings, SQL catalog, and importer."""

from __future__ import annotations

import re

# fullmatch is load-bearing: .match()/.search() would accept injection prefixes.
_WORKSPACE_ID = re.compile(r"[A-Za-z0-9_-]+")
_MAX_WORKSPACE_ID_LENGTH = 64
_WORKSPACE_ID_CONTRACT = (
    "must fullmatch [A-Za-z0-9_-]+ and be at most 64 characters"
)


def parse_workspace_id(raw: str | None) -> str | None:
    """Strip and validate a workspace identifier.

    Empty or whitespace-only values are absent. Present values must match the
    charset and length contract.

    Args:
        raw (str | None): Candidate identifier, typically from configuration.

    Returns:
        str | None: The stripped identifier, or ``None`` when absent.

    Raises:
        ValueError: The stripped value fails the charset or length contract.
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if len(value) > _MAX_WORKSPACE_ID_LENGTH or not _WORKSPACE_ID.fullmatch(value):
        raise ValueError(_WORKSPACE_ID_CONTRACT)
    return value


def require_workspace_id(raw: str | None) -> str:
    """Return a validated workspace id, rejecting absent values.

    Args:
        raw (str | None): Candidate identifier.

    Returns:
        str: The stripped identifier.

    Raises:
        ValueError: The value is absent or fails the charset or length contract.
            The message names ``workspace_id``.
    """
    try:
        parsed = parse_workspace_id(raw)
    except ValueError as error:
        raise ValueError(f"workspace_id {error}") from error
    if parsed is None:
        raise ValueError(f"workspace_id {_WORKSPACE_ID_CONTRACT}")
    return parsed
