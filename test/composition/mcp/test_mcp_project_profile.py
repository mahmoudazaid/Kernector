"""MCP wiring for software_delivery.project_profile (#387 slice 8)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from composition.mcp.access import McpCallerContext
from composition.mcp.project_profile import (
    McpProjectProfileBinding,
    ProjectProfileArgs,
    build_mcp_project_profile_binding,
)
from composition.mcp.tool_registry import TOOL_UNAVAILABLE_CODE, mcp_tool_name
from composition.mcp.wiring import build_mcp_tool_registry
from composition.project_profile.facade import ProjectProfileFacade
from infrastructure.config import DomainToolSettings, load_settings
from packs.software_delivery.tools.project_profile_mcp import TOOL_PROJECT_PROFILE
from test.fixtures.project_intelligence.loader import secret_env_value
from test.packs.software_delivery.project_profile.conftest import load_component_files


class _StubRetrieve:
    def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return ()


def _evidence_args() -> dict[str, object]:
    return {
        "evidence": [
            {
                "component": "oie-orders",
                "files": load_component_files("acme/oie-orders"),
            },
            {
                "component": "oie-tests",
                "files": load_component_files("acme/oie-tests"),
            },
            {
                "component": "oie-e2e",
                "files": load_component_files("acme/oie-e2e"),
            },
            {
                "component": "oie-web",
                "files": load_component_files("acme/oie-web"),
            },
        ]
    }


def _registry(workspace_id: str = "ws-a"):
    base = load_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
        document_catalog=replace(base.document_catalog, workspace_id=workspace_id),
    )
    return build_mcp_tool_registry(settings, retrieve=_StubRetrieve())


def test_project_id_rejected_by_schema() -> None:
    with pytest.raises(Exception):
        ProjectProfileArgs.model_validate(
            {"project_id": "oie", "evidence": [{"files": [{"path": "a", "content": "x"}]}]}
        )


def test_workflow_rejects_project_id_argument() -> None:
    from domain.errors import ToolArgumentValidationError

    binding = McpProjectProfileBinding(lambda: ProjectProfileFacade("ws-a"))
    with pytest.raises(ToolArgumentValidationError, match="project_id"):
        binding.workflow().profile(
            {
                "project_id": "oie",
                "evidence": [
                    {"files": [{"path": "README.md", "content": "hi\n"}]}
                ],
            }
        )


def test_allowlist_deny_cannot_list_or_call() -> None:
    registry = _registry()
    denied = McpCallerContext("ws-a", "default", frozenset())
    assert all(
        item.name != mcp_tool_name(TOOL_PROJECT_PROFILE)
        for item in registry.list_effective(denied)
    )
    result = registry.invoke_authorized(denied, TOOL_PROJECT_PROFILE, _evidence_args())
    assert result.code == TOOL_UNAVAILABLE_CODE


def test_different_profile_ids_same_allowlist_identical_results() -> None:
    registry = _registry()
    args = _evidence_args()
    a = McpCallerContext("ws-a", "profile-a", frozenset({TOOL_PROJECT_PROFILE}))
    b = McpCallerContext("ws-a", "profile-b", frozenset({TOOL_PROJECT_PROFILE}))
    result_a = registry.invoke_authorized(a, TOOL_PROJECT_PROFILE, args)
    result_b = registry.invoke_authorized(b, TOOL_PROJECT_PROFILE, args)
    assert result_a.is_error is False
    assert result_b.is_error is False
    assert result_a.text == result_b.text


def test_cross_workspace_bindings_are_isolated() -> None:
    facade_a = ProjectProfileFacade("ws-a")
    facade_b = ProjectProfileFacade("ws-b")
    assert facade_a.workspace_id != facade_b.workspace_id
    base = load_settings()
    binding_a = build_mcp_project_profile_binding(
        replace(base, document_catalog=replace(base.document_catalog, workspace_id="ws-a")),
        facade_factory=lambda: facade_a,
    )
    binding_b = build_mcp_project_profile_binding(
        replace(base, document_catalog=replace(base.document_catalog, workspace_id="ws-b")),
        facade_factory=lambda: facade_b,
    )
    assert binding_a.workflow()._facade.workspace_id == "ws-a"
    assert binding_b.workflow()._facade.workspace_id == "ws-b"
    payload = {
        "evidence": [
            {
                "component": "oie-tests",
                "files": load_component_files("acme/oie-tests"),
            }
        ]
    }
    out_a = binding_a.workflow().profile(payload)
    out_b = binding_b.workflow().profile(payload)
    assert out_a["profile_fingerprint"] == out_b["profile_fingerprint"]
    assert binding_a.workflow()._facade is not binding_b.workflow()._facade


def test_secret_values_absent_from_mcp_result() -> None:
    registry = _registry()
    caller = McpCallerContext("ws-a", "default", frozenset({TOOL_PROJECT_PROFILE}))
    result = registry.invoke_authorized(caller, TOOL_PROJECT_PROFILE, _evidence_args())
    assert result.is_error is False
    secret = secret_env_value()
    assert secret not in result.text
    assert "sk_live_fixture_secret_value_do_not_echo" not in result.text
    data = json.loads(result.text)
    assert data["untrusted_evidence"] is True
    assert data["approved_conventions"] == []
    assert data["conflicts"] == []
    assert data["evidence_origin"] == "client_supplied"


def test_per_component_robot_and_playwright_detected() -> None:
    registry = _registry()
    caller = McpCallerContext("ws-a", "default", frozenset({TOOL_PROJECT_PROFILE}))
    result = registry.invoke_authorized(caller, TOOL_PROJECT_PROFILE, _evidence_args())
    data = json.loads(result.text)
    by_label = {c["label"]: c for c in data["components"]}
    assert by_label["oie-tests"]["facet_status"]["test_frameworks"] == "detected"
    assert by_label["oie-e2e"]["facet_status"]["test_frameworks"] == "detected"
    assert data["facet_status"].get("test_frameworks") != "ambiguous"


def test_facet_filter_limits_returned_facets() -> None:
    registry = _registry()
    caller = McpCallerContext("ws-a", "default", frozenset({TOOL_PROJECT_PROFILE}))
    args = _evidence_args()
    args["facets"] = ["delivery"]
    result = registry.invoke_authorized(caller, TOOL_PROJECT_PROFILE, args)
    data = json.loads(result.text)
    assert set(data["facet_status"]) <= {"delivery"}
    assert all(f["facet"] == "delivery" for f in data["facts"])


def test_fingerprint_stable_across_identical_calls() -> None:
    registry = _registry()
    caller = McpCallerContext("ws-a", "default", frozenset({TOOL_PROJECT_PROFILE}))
    args = _evidence_args()
    first = json.loads(
        registry.invoke_authorized(caller, TOOL_PROJECT_PROFILE, args).text
    )
    second = json.loads(
        registry.invoke_authorized(caller, TOOL_PROJECT_PROFILE, args).text
    )
    assert first["profile_fingerprint"] == second["profile_fingerprint"]


def test_build_mcp_tools_contributes_project_profile_with_binding() -> None:
    from packs.software_delivery.registration import build_mcp_tools

    contributed = build_mcp_tools(
        project_profile_binding=McpProjectProfileBinding(
            lambda: ProjectProfileFacade("ws")
        )
    )
    assert TOOL_PROJECT_PROFILE in {tool_id for tool_id, _ in contributed}
