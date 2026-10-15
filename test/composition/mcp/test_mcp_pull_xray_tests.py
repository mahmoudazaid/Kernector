"""MCP exposure of software_delivery.pull_xray_tests_to_files (#400)."""

from __future__ import annotations

import json

from composition.mcp.access import McpCallerContext
from composition.mcp.tool_registry import McpToolContribution, McpToolRegistry, mcp_tool_name
from composition.xray_export.test_file_create import XrayFileCreateBinding
from composition.xray_export.test_file_pull import PullXrayTestsToFilesArgs
from domain.tool_approval import ToolApprovalPolicy
from domain.test_management.xray import (
    IssueLinkRef,
    IssueLookupResult,
    JiraIssueSummary,
    StoryNamingContext,
    XrayTestDetails,
    XrayTestDetailsResult,
    XrayTestStep,
)
from packs.software_delivery.registration import build_mcp_tools
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.tools.pull_xray_tests_to_files import (
    TOOL_NAME,
    PullXrayTestsToFilesTool,
)

TAGS = TestFileTagConfig("XRay", "Story", ("manual", "scaffold"))


class _Xray:
    def find_issues(self, keys):
        found = {
            "ABC-1": JiraIssueSummary("ABC-1", "Login", "1", "Story", False),
        }
        return IssueLookupResult(found={k: found[k] for k in keys if k in found}, missing=frozenset())

    def linked_tests(self, story_key: str):
        return (JiraIssueSummary("QA-7", "User logs in", "2", "Test", True),)

    def list_tests(self, project_key: str, *, component: str | None = None):
        return ()

    def story_naming_context(self, story_key: str) -> StoryNamingContext:
        return StoryNamingContext(story_key, "Login", "absent")

    def test_details(self, keys):
        return XrayTestDetailsResult(
            found={
                "QA-7": XrayTestDetails(
                    key="QA-7",
                    issue_id="7",
                    summary="User logs in",
                    kind="manual",
                    steps=(XrayTestStep(action="Go", expected="ok"),),
                    links=(IssueLinkRef("Test", "outward", "ABC-1"),),
                )
            }
        )

    def schema(self):
        raise AssertionError("unused")

    def import_tests(self, specs):
        raise AssertionError("unused")

    def capabilities(self):
        raise AssertionError("unused")

    def update_test(self, patch):
        raise AssertionError("unused")


def _binding() -> XrayFileCreateBinding:
    xray = _Xray()
    return XrayFileCreateBinding(
        importer=xray,  # type: ignore[arg-type]
        lookup=xray,
        updater=xray,  # type: ignore[arg-type]
        tags=TAGS,
        project_key="QA",
        destination_label="Jira project QA",
        story_issue_types=frozenset({"Story"}),
        link_type="Test",
    )


def test_xray_file_binding_contributes_pull_tool_with_approval() -> None:
    tools = dict(build_mcp_tools(xray_file_binding=_binding()))

    tool = tools[TOOL_NAME]()
    assert type(tool) is PullXrayTestsToFilesTool
    assert tool.args_schema is PullXrayTestsToFilesArgs
    assert ToolApprovalPolicy().requires_approval(TOOL_NAME) is True


def test_invoke_pull_returns_proposals() -> None:
    contributions = tuple(
        McpToolContribution(tool_id, "software-delivery", factory)
        for tool_id, factory in build_mcp_tools(xray_file_binding=_binding())
    )
    registry = McpToolRegistry(contributions=contributions, enabled_packs=("software-delivery",))
    caller = McpCallerContext("ws", "default", frozenset({TOOL_NAME}))

    [descriptor] = registry.list_effective(caller)
    assert descriptor.name == mcp_tool_name(TOOL_NAME)
    assert set(descriptor.input_schema["properties"]) >= {
        "story_key",
        "project",
        "files",
        "formats",
        "dry_run",
        "new_file_paths",
        "new_file_name_template",
    }

    result = registry.invoke_authorized(
        caller,
        TOOL_NAME,
        {"story_key": "ABC-1", "files": [], "dry_run": True},
        approve=lambda _pending: True,
    )
    assert result.is_error is False
    payload = json.loads(result.text)
    assert payload["results"][0]["status"] == "WOULD_NEW_FILE"
    assert payload["files"] == []
