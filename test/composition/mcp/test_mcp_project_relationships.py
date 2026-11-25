"""Read-only MCP tool ``core.project_relationships`` (#374)."""

from __future__ import annotations

import pytest

from composition.mcp.access import McpCallerContext
from composition.mcp.project_relationships import TOOL_NAME, ProjectRelationshipsTool
from composition.mcp.tool_registry import (
    TOOL_UNAVAILABLE_CODE,
    McpToolContribution,
    McpToolRegistry,
)
from domain.errors import ToolArgumentValidationError


class _EmptyList:
    def execute(self, project_id: str, key: str, *, filters=None):  # noqa: ANN001
        del project_id, key, filters
        return ()


def _registry(list_relationships: object) -> McpToolRegistry:
    return McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id=TOOL_NAME,
                pack_id=None,
                factory=lambda: ProjectRelationshipsTool(list_relationships),  # type: ignore[arg-type]
            ),
        ),
        enabled_packs=(),
    )


def test_tool_is_denied_unless_allowlisted() -> None:
    caller = McpCallerContext("ws", "default", "prj_test", frozenset())

    result = _registry(_EmptyList()).invoke_authorized(caller, TOOL_NAME, {"key": "X"})

    assert result.is_error
    assert result.code == TOOL_UNAVAILABLE_CODE


def test_tool_rejects_mismatched_project_id() -> None:
    tool = ProjectRelationshipsTool(_EmptyList())  # type: ignore[arg-type]
    from composition.mcp.access import bind_caller

    with bind_caller(
        McpCallerContext("ws", "default", "prj_a", frozenset({TOOL_NAME}))
    ):
        with pytest.raises(ToolArgumentValidationError):
            tool.run({"key": "PROJ-123", "project_id": "prj_b"})


def test_wiring_contributes_core_project_relationships() -> None:
    from composition.mcp.wiring import build_mcp_tool_registry
    from infrastructure.config import load_settings

    class _Retrieve:
        def execute(self, request: object) -> object:
            raise AssertionError("not called")

    from composition.mcp.tool_registry import mcp_tool_name

    registry = build_mcp_tool_registry(load_settings(), retrieve=_Retrieve())  # type: ignore[arg-type]
    caller = McpCallerContext("ws", "default", "prj_test", frozenset({TOOL_NAME}))
    assert mcp_tool_name(TOOL_NAME) in {
        item.name for item in registry.list_effective(caller)
    }
