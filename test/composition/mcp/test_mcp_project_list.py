"""Read-only MCP tool ``core.project_list`` (#372)."""

from __future__ import annotations

import json

from application.project.projects import ListProjects
from composition.mcp.access import McpCallerContext
from composition.mcp.project_list import TOOL_NAME, ProjectListTool
from composition.mcp.tool_registry import (
    TOOL_UNAVAILABLE_CODE,
    McpToolContribution,
    McpToolRegistry,
    mcp_tool_name,
)
from domain.project.models import (
    AssociationState,
    Project,
    SourceAssociation,
    SourceScope,
)
from test.application.project.project_fakes import InMemoryProjectStore, confirmed

ORDERS = SourceScope("gh-1", "repo", "acme/oie-orders")
DOCS = SourceScope("gh-1", "repo", "acme/oie-docs")


def _registry(store: InMemoryProjectStore) -> McpToolRegistry:
    return McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id=TOOL_NAME,
                pack_id=None,
                factory=lambda: ProjectListTool(ListProjects(store=store)),
            ),
        ),
        enabled_packs=(),
    )


def _store() -> InMemoryProjectStore:
    store = InMemoryProjectStore()
    with store.transaction() as tx:
        tx.projects.add(Project("prj_oie", "Order Intake", "oie", 1))
        tx.associations.add(confirmed("prj_oie", ORDERS, ("backend", "api_contract")))
        tx.associations.add(
            SourceAssociation(
                "prj_oie", DOCS, (), AssociationState.SUGGESTED, (), "evidence", 1
            )
        )
    return store


def test_tool_is_denied_unless_allowlisted() -> None:
    caller = McpCallerContext("ws", "default", frozenset())

    result = _registry(_store()).invoke_authorized(caller, TOOL_NAME, {})

    assert result.is_error
    assert result.code == TOOL_UNAVAILABLE_CODE
    assert list(_registry(_store()).list_effective(caller)) == []


def test_tool_returns_projects_with_confirmed_associations_only() -> None:
    caller = McpCallerContext("ws", "default", frozenset({TOOL_NAME}))

    result = _registry(_store()).invoke_authorized(caller, mcp_tool_name(TOOL_NAME), {})

    assert not result.is_error, result.text
    payload = json.loads(result.text)
    assert payload == {
        "projects": [
            {
                "project_id": "prj_oie",
                "name": "Order Intake",
                "slug": "oie",
                "confirmed_associations": [
                    {
                        "connector_id": "gh-1",
                        "scope_kind": "repo",
                        "scope_value": "acme/oie-orders",
                        "roles": ["backend", "api_contract"],
                    }
                ],
            }
        ]
    }


def test_tool_rejects_unexpected_arguments() -> None:
    caller = McpCallerContext("ws", "default", frozenset({TOOL_NAME}))

    result = _registry(_store()).invoke_authorized(caller, TOOL_NAME, {"x": 1})

    assert result.is_error


def test_wiring_contributes_core_project_list() -> None:
    from composition.mcp.wiring import build_mcp_tool_registry
    from infrastructure.config import load_settings

    class _Retrieve:
        def execute(self, request: object) -> object:
            raise AssertionError("not called")

    registry = build_mcp_tool_registry(load_settings(), retrieve=_Retrieve())  # type: ignore[arg-type]
    caller = McpCallerContext("ws", "default", frozenset({TOOL_NAME}))

    assert [item.name for item in registry.list_effective(caller)] == [
        mcp_tool_name(TOOL_NAME)
    ]
