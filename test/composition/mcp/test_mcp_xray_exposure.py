"""MCP exposure of software_delivery.create_xray_tests (ADR 0010, #199)."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from composition.mcp.access import McpCallerContext
from composition.mcp.tool_registry import (
    APPROVAL_DECLINED_CODE,
    APPROVAL_REQUIRED_CODE,
    TOOL_UNAVAILABLE_CODE,
    VALIDATION_ERROR_CODE,
    McpToolContribution,
    McpToolRegistry,
    mcp_tool_name,
)
from composition.xray_export.mcp import XrayMcpBinding
from domain.test_management.xray import XrayImportResult, XrayTestCreateSchema, XrayTestSpec
from domain.tool_approval import PendingToolApproval
from packs.software_delivery.registration import build_mcp_tools
from packs.software_delivery.tools.create_xray_tests import TOOL_NAME, CreateXrayTestsTool
from test.packs.software_delivery.tools.test_create_xray_tests import (
    _candidate,
    _draft,
    _manual_case,
)


class _Importer:
    def __init__(self) -> None:
        self.schema_calls = 0
        self.imports: list[tuple[XrayTestSpec, ...]] = []

    def schema(self) -> XrayTestCreateSchema:
        self.schema_calls += 1
        return XrayTestCreateSchema("QA", True, True, True)

    def import_tests(self, specs: Sequence[XrayTestSpec]) -> XrayImportResult:
        self.imports.append(tuple(specs))
        return XrayImportResult(created_keys=("QA-7", "QA-8"), failed_count=1)


def _binding(importer: _Importer) -> XrayMcpBinding:
    draft = _draft(
        candidates=(_candidate("cand-1"), _candidate("cand-2")),
        cases=(_manual_case("cand-1"), _manual_case("cand-2")),
    )
    return XrayMcpBinding(
        importer=importer,
        load_draft=lambda draft_id: draft if draft_id == "draft-1" else None,
        project_key="QA",
    )


def _registry(importer: _Importer) -> McpToolRegistry:
    contributions = tuple(
        McpToolContribution(tool_id, "software-delivery", factory)
        for tool_id, factory in build_mcp_tools(xray_binding=_binding(importer))
    )
    return McpToolRegistry(contributions=contributions, enabled_packs=("software-delivery",))


def _caller(*tool_ids: str) -> McpCallerContext:
    return McpCallerContext("ws", "default", frozenset(tool_ids))


class _Gate:
    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.requests: list[PendingToolApproval] = []

    def __call__(self, request: PendingToolApproval) -> bool:
        self.requests.append(request)
        return self.answer


def test_build_mcp_tools_contributes_the_same_tool_class_only_with_a_binding() -> None:
    assert build_mcp_tools() == ()

    [(tool_id, factory)] = build_mcp_tools(xray_binding=_binding(_Importer()))

    assert tool_id == TOOL_NAME
    assert type(factory()) is CreateXrayTestsTool


def test_listing_is_gated_by_the_allowlist_and_advertises_a_strict_schema() -> None:
    registry = _registry(_Importer())

    assert registry.list_effective(_caller()) == ()
    [descriptor] = registry.list_effective(_caller(TOOL_NAME))
    assert descriptor.name == mcp_tool_name(TOOL_NAME)
    schema = descriptor.input_schema
    assert set(schema["properties"]) == {"draft_id", "link_source_issue"}
    assert schema["required"] == ["draft_id"]
    assert schema["additionalProperties"] is False


def test_unauthorized_caller_is_unavailable_and_never_reaches_xray() -> None:
    importer = _Importer()

    result = _registry(importer).invoke_authorized(
        _caller(), TOOL_NAME, {"draft_id": "draft-1"}, approve=_Gate(True)
    )

    assert result.code == TOOL_UNAVAILABLE_CODE
    assert (importer.schema_calls, importer.imports) == (0, [])


@pytest.mark.parametrize(
    ("approve", "code"),
    [(None, APPROVAL_REQUIRED_CODE), (_Gate(False), APPROVAL_DECLINED_CODE)],
)
def test_missing_or_declined_approval_never_reaches_xray(approve, code: str) -> None:  # noqa: ANN001
    importer = _Importer()

    result = _registry(importer).invoke_authorized(
        _caller(TOOL_NAME), TOOL_NAME, {"draft_id": "draft-1"}, approve=approve
    )

    assert result.code == code
    assert (importer.schema_calls, importer.imports) == (0, [])


def test_approved_call_creates_once_and_returns_the_safe_receipt() -> None:
    importer = _Importer()
    gate = _Gate(True)

    result = _registry(importer).invoke_authorized(
        _caller(TOOL_NAME), TOOL_NAME, {"draft_id": "draft-1"}, approve=gate
    )

    assert result.is_error is False
    assert len(importer.imports) == 1
    assert json.loads(result.text) == {
        "created_keys": ["QA-7", "QA-8"],
        "created_count": 2,
        "failed_count": 1,
    }
    [request] = gate.requests
    assert (request.title, request.destination_label, request.selected_title_count) == (
        "Create Xray tests",
        "QA",
        2,
    )
    assert "draft-1" not in repr(request)


def test_unknown_draft_is_rejected_before_the_gate() -> None:
    importer = _Importer()
    gate = _Gate(True)

    result = _registry(importer).invoke_authorized(
        _caller(TOOL_NAME), TOOL_NAME, {"draft_id": "other-workspace"}, approve=gate
    )

    assert result.code == VALIDATION_ERROR_CODE
    assert gate.requests == []
    assert (importer.schema_calls, importer.imports) == (0, [])


def test_mcp_registry_contributes_xray_only_when_configured(monkeypatch) -> None:  # noqa: ANN001
    from composition.mcp.wiring import build_mcp_tool_registry
    from infrastructure.config import load_settings

    for name in ("XRAY_DEPLOYMENT", "JIRA_OAUTH_CLIENT_ID", "JIRA_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    caller = _caller(TOOL_NAME)

    registry = build_mcp_tool_registry(load_settings(), retrieve=object())  # type: ignore[arg-type]
    assert registry.list_effective(caller) == ()

    monkeypatch.setenv("XRAY_DEPLOYMENT", "cloud")
    monkeypatch.setenv("XRAY_PROJECT_KEY", "QA")
    monkeypatch.setenv("XRAY_CLIENT_ID", "client-id")
    monkeypatch.setenv("XRAY_CLIENT_SECRET", "client-secret")

    registry = build_mcp_tool_registry(load_settings(), retrieve=object())  # type: ignore[arg-type]
    names = [item.name for item in registry.list_effective(caller)]
    assert names == [mcp_tool_name(TOOL_NAME)]
