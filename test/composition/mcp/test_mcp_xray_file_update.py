"""Chat and MCP exposure of software_delivery.update_xray_tests_from_files (#398)."""

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
from composition.xray_export.test_file_create import (
    XrayFileCreateBinding,
    build_xray_file_create_binding,
)
from domain.test_management.xray import (
    IssueLinkRef,
    IssueLookupResult,
    JiraIssueSummary,
    XrayImportResult,
    XrayTestCreateSchema,
    XrayTestDetails,
    XrayTestDetailsResult,
    XrayTestPatch,
    XrayTestSpec,
    XrayUpdateCapabilities,
)
from domain.tool_approval import ToolApprovalPolicy
from infrastructure.config import load_settings
from packs.software_delivery.registration import build_mcp_tools
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.tools.update_xray_tests_from_files import (
    TOOL_NAME,
    UpdateXrayTestsFromFilesTool,
)
from test.composition.mcp.test_mcp_xray_exposure import _Gate

TAGS = TestFileTagConfig("XRay", "Story", ("manual",))
FEATURE = (
    "@Story:ABC-1\nFeature: F\n  @XRay:QA-7\n  Scenario: Login\n    Given x\n    Then y\n"
)
ARGS = {"files": [{"path": "f/a.feature", "content": FEATURE}]}
LABEL = "Jira project QA (Xray Cloud)"


class _Xray:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.patches: list[XrayTestPatch] = []

    def schema(self) -> XrayTestCreateSchema:
        self.calls.append("schema")
        return XrayTestCreateSchema("QA", True, True, True, supports_cucumber_outline=True)

    def import_tests(self, specs: Sequence[XrayTestSpec]) -> XrayImportResult:
        self.calls.append("import")
        return XrayImportResult(created_keys=(), failed_count=0)

    def find_issues(self, keys: Sequence[str]) -> IssueLookupResult:
        self.calls.append("find")
        return IssueLookupResult(
            found={
                "ABC-1": JiraIssueSummary("ABC-1", "Story", "10001", "Story", False),
                "QA-7": JiraIssueSummary("QA-7", "Old login", "10002", "Test", True),
            }
        )

    def linked_tests(self, story_key: str) -> tuple[JiraIssueSummary, ...]:
        self.calls.append("linked")
        return ()

    def capabilities(self) -> XrayUpdateCapabilities:
        self.calls.append("capabilities")
        return XrayUpdateCapabilities(jira_fields=True, story_link_type=True)

    def test_details(self, keys: Sequence[str]) -> XrayTestDetailsResult:
        self.calls.append("details")
        details = XrayTestDetails(
            key="QA-7",
            issue_id="10007",
            summary="Old login",
            kind="cucumber",
            project_key="QA",
            scenario_type="scenario",
            gherkin="Given x\nThen y",
            links=(IssueLinkRef("Test", "outward", "ABC-1"),),
            editable=frozenset({"summary", "gherkin", "story_link"}),
        )
        return XrayTestDetailsResult(found={"QA-7": details})

    def update_test(self, patch: XrayTestPatch) -> None:
        self.calls.append("update")
        self.patches.append(patch)


def _binding(xray: _Xray) -> XrayFileCreateBinding:
    return XrayFileCreateBinding(
        importer=xray,
        lookup=xray,
        updater=xray,
        tags=TAGS,
        project_key="QA",
        destination_label=LABEL,
        story_issue_types=frozenset({"Story"}),
        link_type="Test",
    )


def _registry(xray: _Xray) -> McpToolRegistry:
    contributions = tuple(
        McpToolContribution(tool_id, "software-delivery", factory)
        for tool_id, factory in build_mcp_tools(xray_file_binding=_binding(xray))
    )
    return McpToolRegistry(contributions=contributions, enabled_packs=("software-delivery",))


def _caller(*tool_ids: str) -> McpCallerContext:
    return McpCallerContext("ws", "default", frozenset(tool_ids))


def test_build_mcp_tools_contributes_the_update_tool_with_a_binding() -> None:
    tools = dict(build_mcp_tools(xray_file_binding=_binding(_Xray())))

    assert type(tools[TOOL_NAME]()) is UpdateXrayTestsFromFilesTool


def test_every_call_requires_approval() -> None:
    assert ToolApprovalPolicy().requires_approval(TOOL_NAME) is True


def test_listing_advertises_a_strict_schema() -> None:
    registry = _registry(_Xray())

    assert registry.list_effective(_caller()) == ()
    [descriptor] = registry.list_effective(_caller(TOOL_NAME))
    assert descriptor.name == mcp_tool_name(TOOL_NAME)
    schema = descriptor.input_schema
    assert set(schema["properties"]) == {"files", "dry_run"}
    assert schema["required"] == ["files"]
    assert schema["additionalProperties"] is False
    assert descriptor.output_schema is not None


@pytest.mark.parametrize(
    "arguments",
    [{**ARGS, "extra": 1}, {**ARGS, "dry_run": "yes"}, {"files": []}],
    ids=["extra", "dry-run-not-bool", "no-files"],
)
def test_invalid_arguments_are_rejected_before_the_gate(arguments: dict[str, object]) -> None:
    xray = _Xray()
    gate = _Gate(True)

    result = _registry(xray).invoke_authorized(
        _caller(TOOL_NAME), TOOL_NAME, arguments, approve=gate
    )

    assert result.code == VALIDATION_ERROR_CODE
    assert (gate.requests, xray.calls) == ([], [])


def test_unauthorized_caller_never_reaches_xray() -> None:
    xray = _Xray()

    result = _registry(xray).invoke_authorized(_caller(), TOOL_NAME, ARGS, approve=_Gate(True))

    assert result.code == TOOL_UNAVAILABLE_CODE
    assert xray.calls == []


@pytest.mark.parametrize(
    ("approve", "code"),
    [(None, APPROVAL_REQUIRED_CODE), (_Gate(False), APPROVAL_DECLINED_CODE)],
    ids=["missing", "declined"],
)
@pytest.mark.parametrize("dry_run", [True, False])
def test_missing_or_declined_approval_never_reaches_xray(
    approve, code: str, dry_run: bool  # noqa: ANN001
) -> None:
    xray = _Xray()

    result = _registry(xray).invoke_authorized(
        _caller(TOOL_NAME), TOOL_NAME, {**ARGS, "dry_run": dry_run}, approve=approve
    )

    assert result.code == code
    assert xray.calls == []


def test_approved_dry_run_returns_the_plan_without_updating() -> None:
    xray = _Xray()
    gate = _Gate(True)

    result = _registry(xray).invoke_authorized(
        _caller(TOOL_NAME), TOOL_NAME, {**ARGS, "dry_run": True}, approve=gate
    )

    assert result.is_error is False
    payload = json.loads(result.text)
    assert payload == result.structured
    [entry] = payload["results"]
    assert (entry["status"], entry["key"], entry["changes"]) == ("WOULD_UPDATE", "QA-7", ["summary"])
    assert payload["counts"] == {"UPDATED": 0, "WOULD_UPDATE": 1, "SKIPPED": 0, "ERROR": 0}
    assert "update" not in xray.calls
    [request] = gate.requests
    assert request.title.startswith("Dry run")
    assert (request.destination_label, request.item_titles) == (LABEL, ("a.feature:4 · Login",))
    assert "Given" not in repr(request)


def test_approved_run_updates_only_the_changed_field() -> None:
    xray = _Xray()

    result = _registry(xray).invoke_authorized(
        _caller(TOOL_NAME), TOOL_NAME, ARGS, approve=_Gate(True)
    )

    assert result.is_error is False
    assert result.structured is not None
    assert result.structured["results"][0]["status"] == "UPDATED"
    assert xray.patches == [XrayTestPatch(key="QA-7", issue_id="10007", summary="Login")]


def test_binding_wires_the_client_as_updater(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "XRAY_DEPLOYMENT": "cloud",
        "XRAY_PROJECT_KEY": "QA",
        "XRAY_CLIENT_ID": "client-id",
        "XRAY_CLIENT_SECRET": "client-secret",
    }.items():
        monkeypatch.setenv(name, value)

    binding = build_xray_file_create_binding(load_settings())

    assert binding is not None
    assert binding.updater is binding.lookup
    assert binding.link_type
