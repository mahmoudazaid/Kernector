"""Composition re-export of MCP isolation gates (#324)."""

from __future__ import annotations

from domain.mcp_access.isolation import (
    is_isolation_safe,
    isolation_unsafe_tool_ids,
)

ISOLATION_BLOCKED_REASON = (
    "Tool cannot guarantee project isolation until workspace index scoping "
    "lands (#257 / #377)."
)

__all__ = [
    "ISOLATION_BLOCKED_REASON",
    "is_isolation_safe",
    "isolation_unsafe_tool_ids",
]
