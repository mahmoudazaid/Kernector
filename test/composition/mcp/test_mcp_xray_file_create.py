"""Chat and MCP exposure of software_delivery.create_xray_tests_from_files (#397)."""

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
    IssueLookupResult,
    JiraIssueSummary,
    XrayImportResult,
    XrayTestCreateSchema,
    XrayTestSpec,
)
from domain.tool_approval import ToolApprovalPolicy
from infrastructure.config import load_settings
from packs.software_delivery.registration import build_mcp_tools
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.tools.create_xray_tests_from_files import (
    TOOL_NAME,
    CreateXrayTestsFromFilesTool,
)
from packs.software_delivery.tools.xray_target import TOOL_NAME as TARGET_TOOL
from packs.software_delivery.tools.xray_target import XrayTargetTool
from test.composition.mcp.test_mcp_xray_exposure import _Gate

TAGS = TestFileTagConfig("XRay", "Story", ("manual",))
FEATURE = "@Story:ABC-1\nFeature: F\n  Scenario: Login\n    Given x\n    Then y\n"
ARGS = {"files": [{"path": "f/a.feature", "content": FEATURE}]}
LABEL = "Jira project QA (Xray Cloud)"


class _Xray:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def schema(self) -> XrayTestCreateSchema:
        self.calls.append("schema")
        return XrayTestCreateSchema("QA", True, True, True, supports_cucumber_outline=True)

    def import_tests(self, specs: Sequence[XrayTestSpec]) -> XrayImportResult:
        self.calls.append("import")
        return XrayImportResult(created_keys=("QA-9",), failed_count=0)

    def find_issues(self, keys: Sequence[str]) -> IssueLookupResult:
        self.calls.append("find")
        story = JiraIssueSummary("ABC-1", "Story", "10001", "Story", False)
        return IssueLookupResult(found={"ABC-1": story})

    def linked_tests(self, story_key: str) -> tuple[JiraIssueSummary, ...]:
        self.calls.append("linked")
        return ()


def _binding(xray: _Xray) -> XrayFileCreateBinding:
    return XrayFileCreateBinding(
        importer=xray,
        lookup=xray,
        updater=xray,  # type: ignore[arg-type]
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


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in (
        "XRAY_DEPLOYMENT",
        "XRAY_PROJECT_KEY",
        "XRAY_CLIENT_ID",
        "XRAY_CLIENT_SECRET",
        "XRAY_TEST_TAG",
        "XRAY_STORY_TAG",
        "XRAY_MANUAL_TAGS",
        "XRAY_DEFAULT_COMPONENT",
        "XRAY_STORY_ISSUE_TYPES",
        "JIRA_OAUTH_CLIENT_ID",
        "JIRA_OAUTH_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    return monkeypatch


def _cloud(env: pytest.MonkeyPatch) -> None:
    env.setenv("XRAY_DEPLOYMENT", "cloud")
    env.setenv("XRAY_PROJECT_KEY", "QA")
    env.setenv("XRAY_CLIENT_ID", "client-id")
    env.setenv("XRAY_CLIENT_SECRET", "client-secret")


def test_build_mcp_tools_contributes_the_tools_only_with_a_binding() -> None:
    assert build_mcp_tools() == ()

    tools = dict(build_mcp_tools(xray_file_binding=_binding(_Xray())))

    assert set(tools) == {TOOL_NAME, TARGET_TOOL, "software_delivery.update_xray_tests_from_files"}
    assert type(tools[TOOL_NAME]()) is CreateXrayTestsFromFilesTool
    assert type(tools[TARGET_TOOL]()) is XrayTargetTool


def test_target_tool_runs_without_approval_and_names_the_destination() -> None:
    xray = _Xray()

    result = _registry(xray).invoke_authorized(_caller(TARGET_TOOL), TARGET_TOOL, {})

    assert result.is_error is False
    assert result.structured is not None
    assert result.structured["destination"] == LABEL
    assert result.structured["project_key"] == "QA"
    assert xray.calls == ["schema"]


def test_target_tool_rejects_arguments() -> None:
    result = _registry(_Xray()).invoke_authorized(
        _caller(TARGET_TOOL), TARGET_TOOL, {"project_key": "OIE"}
    )

    assert result.code == VALIDATION_ERROR_CODE


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
    [
        {**ARGS, "extra": 1},
        {**ARGS, "dry_run": "yes"},
        {"files": []},
        {"files": [{"path": "a.feature", "content": FEATURE, "x": 1}]},
    ],
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


def test_approved_call_returns_the_structured_result_and_safe_prompt() -> None:
    xray = _Xray()
    gate = _Gate(True)

    result = _registry(xray).invoke_authorized(_caller(TOOL_NAME), TOOL_NAME, ARGS, approve=gate)

    assert result.is_error is False
    payload = json.loads(result.text)
    assert payload == result.structured
    assert payload["created"] == {"f/a.feature::Login": "QA-9"}
    assert payload["results"][0]["status"] == "CREATED"
    assert payload["destination"] == LABEL
    [request] = gate.requests
    assert (request.destination_label, request.selected_title_count) == (LABEL, 1)
    assert request.item_titles == ("a.feature:3 · Login",)
    assert "Given" not in repr(request)


def test_binding_is_built_only_when_xray_is_configured(env: pytest.MonkeyPatch) -> None:
    assert build_xray_file_create_binding(load_settings()) is None

    _cloud(env)
    env.setenv("XRAY_DEFAULT_COMPONENT", "Checkout")
    env.setenv("XRAY_STORY_ISSUE_TYPES", "Story,User Story")
    binding = build_xray_file_create_binding(load_settings())

    assert binding is not None
    assert binding.project_key == "QA"
    assert binding.default_component == "Checkout"
    assert binding.story_issue_types == frozenset({"Story", "User Story"})
    assert binding.importer is binding.lookup
    assert binding.destination_label == "Jira project QA (Xray Cloud)"


def test_server_binding_names_the_jira_host(env: pytest.MonkeyPatch) -> None:
    env.setenv("XRAY_DEPLOYMENT", "server")
    env.setenv("XRAY_PROJECT_KEY", "QA")
    env.setenv("JIRA_DC_BASE_URL", "https://jira.example.test/jira")
    env.setenv("JIRA_DC_TOKEN", "dc-token")

    binding = build_xray_file_create_binding(load_settings())

    assert binding is not None
    assert binding.destination_label == "Jira project QA on jira.example.test"


def test_mcp_wiring_contributes_the_tools_only_when_configured(env: pytest.MonkeyPatch) -> None:
    from composition.mcp.wiring import build_mcp_tool_registry

    caller = _caller(TOOL_NAME, TARGET_TOOL)
    registry = build_mcp_tool_registry(load_settings(), retrieve=object())  # type: ignore[arg-type]
    assert registry.list_effective(caller) == ()

    _cloud(env)
    registry = build_mcp_tool_registry(load_settings(), retrieve=object())  # type: ignore[arg-type]
    assert {item.name for item in registry.list_effective(caller)} == {
        mcp_tool_name(TOOL_NAME),
        mcp_tool_name(TARGET_TOOL),
    }


def test_chat_registry_lists_the_tool_with_a_binding(env: pytest.MonkeyPatch) -> None:
    from composition.tools.registry import build_tool_registry

    settings = load_settings()

    assert TOOL_NAME not in build_tool_registry(settings).names()
    registry = build_tool_registry(settings, xray_file_binding=_binding(_Xray()))
    assert {TOOL_NAME, TARGET_TOOL} <= set(registry.names())


def test_chat_wiring_registers_the_tool_only_when_configured(env: pytest.MonkeyPatch) -> None:
    from composition.container import build_invoke_tool

    assert TOOL_NAME not in build_invoke_tool(load_settings())._registry  # noqa: SLF001

    _cloud(env)
    assert TOOL_NAME in build_invoke_tool(load_settings())._registry  # noqa: SLF001

    env.delenv("DOMAIN_TOOL_PACKS")
    assert TOOL_NAME not in build_invoke_tool(load_settings())._registry  # noqa: SLF001
