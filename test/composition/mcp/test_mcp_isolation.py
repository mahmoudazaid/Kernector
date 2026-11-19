"""Project/workspace isolation for MCP access profiles (#324 Slice E)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.mcp_access.profiles import (
    CreateAccessProfile,
    CreateAccessProfileRequest,
    UpdateAccessProfileAllowlist,
)
from application.project.projects import ListProjects
from composition.mcp.access import McpCallerContext
from composition.mcp.isolation import is_isolation_safe
from composition.mcp.project_list import TOOL_NAME as PROJECT_LIST
from composition.mcp.project_list import ProjectListTool
from composition.mcp.search_knowledge import TOOL_NAME as SEARCH_TOOL
from composition.mcp.tool_registry import (
    TOOL_UNAVAILABLE_CODE,
    McpToolContribution,
    McpToolRegistry,
)
from domain.mcp_access.errors import IsolationUnsafeToolError
from domain.project.models import Project
from infrastructure.mcp_access.sql_store import SqlMcpAccessProfileStore
from infrastructure.project.sql_store import SqlProjectStore


def test_search_knowledge_is_not_isolation_safe() -> None:
    assert is_isolation_safe(SEARCH_TOOL) is False
    assert is_isolation_safe(PROJECT_LIST) is True


def test_empty_allowlist_lists_nothing_and_invoke_unavailable() -> None:
    registry = McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id=PROJECT_LIST,
                pack_id=None,
                factory=lambda: ProjectListTool(_FakeList()),
            ),
        ),
        enabled_packs=(),
    )
    caller = McpCallerContext("ws-a", "mcp_1", "prj_a", frozenset())
    assert registry.list_effective(caller) == ()
    result = registry.invoke_authorized(caller, PROJECT_LIST, {})
    assert result.is_error
    assert result.code == TOOL_UNAVAILABLE_CODE


def test_non_isolating_tool_never_effective_even_when_allowlisted() -> None:
    from composition.mcp.search_knowledge import SearchKnowledgeTool

    class _StubRetrieve:
        def execute(self, request):  # noqa: ANN001
            raise AssertionError("must not run")

    registry = McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id=SEARCH_TOOL,
                pack_id=None,
                factory=lambda: SearchKnowledgeTool(_StubRetrieve()),
            ),
        ),
        enabled_packs=(),
    )
    caller = McpCallerContext("ws-a", "mcp_1", "prj_a", frozenset({SEARCH_TOOL}))
    assert registry.list_effective(caller) == ()
    result = registry.invoke_authorized(caller, SEARCH_TOOL, {"query": "x"})
    assert result.is_error
    assert result.code == TOOL_UNAVAILABLE_CODE


def test_project_list_returns_only_bound_project(tmp_path: Path) -> None:
    store = SqlProjectStore(tmp_path / "c.sqlite", "ws-a")
    with store.transaction() as tx:
        tx.projects.add(Project("prj_a", "A", "a", 1))
        tx.projects.add(Project("prj_b", "B", "b", 1))
    tool = ProjectListTool(ListProjects(store=store))
    registry = McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id=PROJECT_LIST, pack_id=None, factory=lambda: tool
            ),
        ),
        enabled_packs=(),
    )
    caller = McpCallerContext("ws-a", "mcp_1", "prj_a", frozenset({PROJECT_LIST}))
    result = registry.invoke_authorized(caller, PROJECT_LIST, {})
    assert not result.is_error
    payload = json.loads(result.text)
    assert [p["project_id"] for p in payload["projects"]] == ["prj_a"]


def test_project_id_argument_mismatch_is_rejected() -> None:
    class _Tool:
        name = "software_delivery.fake"
        description = "fake"
        args_schema = None

        def run(self, arguments):  # noqa: ANN001
            raise AssertionError("must not run")

    registry = McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id="software_delivery.fake",
                pack_id="software-delivery",
                factory=lambda: _Tool(),
            ),
        ),
        enabled_packs=("software-delivery",),
    )
    caller = McpCallerContext(
        "ws-a", "mcp_1", "prj_a", frozenset({"software_delivery.fake"})
    )
    result = registry.invoke_authorized(
        caller, "software_delivery.fake", {"project_id": "prj_b"}
    )
    assert result.is_error
    assert result.code == TOOL_UNAVAILABLE_CODE


def test_allowlist_update_rejects_isolation_unsafe_tools(tmp_path: Path) -> None:
    catalog = tmp_path / "c.sqlite"
    with SqlProjectStore(catalog, "ws-a").transaction() as tx:
        tx.projects.add(Project("prj_a", "A", "a", 1))
    profiles = SqlMcpAccessProfileStore(catalog, "ws-a")
    created = CreateAccessProfile(store=profiles).execute(
        CreateAccessProfileRequest(project_id="prj_a", name="dev")
    )
    with pytest.raises(IsolationUnsafeToolError):
        UpdateAccessProfileAllowlist(store=profiles).execute(
            created.profile.profile_id, allowlist=frozenset({SEARCH_TOOL})
        )


def test_side_effect_tool_still_requires_hitl_when_allowlisted() -> None:
    from composition.mcp.tool_registry import APPROVAL_REQUIRED_CODE
    from domain.tool_approval import ToolApprovalPolicy

    class _SideEffect:
        name = "software_delivery.side"
        description = "side"
        args_schema = None

        def run(self, arguments):  # noqa: ANN001
            return "done"

    registry = McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id="software_delivery.side",
                pack_id="software-delivery",
                factory=lambda: _SideEffect(),
            ),
        ),
        enabled_packs=("software-delivery",),
        approval_policy=ToolApprovalPolicy(
            require_approval=frozenset({"software_delivery.side"})
        ),
    )
    caller = McpCallerContext(
        "ws-a", "mcp_1", "prj_a", frozenset({"software_delivery.side"})
    )
    result = registry.invoke_authorized(caller, "software_delivery.side", {})
    assert result.is_error
    assert result.code == APPROVAL_REQUIRED_CODE


class _FakeList:
    def execute(self):
        return ()
