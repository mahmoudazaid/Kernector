"""Isolation-safe MCP tool ids for access-profile allowlists (#324)."""

from __future__ import annotations

# Known-unsafe until #257 / #377 provide project-scoped retrieval.
_ISOLATION_UNSAFE_TOOL_IDS: frozenset[str] = frozenset({"core.search_knowledge"})


def is_isolation_safe(tool_id: str) -> bool:
    """Return False when *tool_id* must not be allowlisted or invoked."""
    return tool_id not in _ISOLATION_UNSAFE_TOOL_IDS


def isolation_unsafe_tool_ids() -> frozenset[str]:
    """Return the set of tool ids blocked for isolation."""
    return _ISOLATION_UNSAFE_TOOL_IDS
