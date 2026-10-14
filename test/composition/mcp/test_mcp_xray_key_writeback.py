"""MCP exposure of software_delivery.write_xray_keys_to_files (#399).

The tool has no Jira/Xray client, so there is nothing to fake: these tests
run with no Xray binding and no ``XRAY_*`` deployment configured.
"""

from __future__ import annotations

import json

import pytest

from composition.mcp.access import McpCallerContext
from composition.mcp.tool_registry import (
    VALIDATION_ERROR_CODE,
    McpToolContribution,
    McpToolRegistry,
    mcp_tool_name,
)
from composition.xray_export.test_file_preview import TestFilePreviewMcpBinding
from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.registration import build_mcp_tools
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.tools.write_xray_keys_to_files import (
    TOOL_NAME,
    WriteXrayKeysToFilesTool,
)

TAGS = TestFileTagConfig("XRay", "Story", ("manual",))
FEATURE = "Feature: F\n  Scenario: S\n    Given x\n"
FILES = [{"path": "f/a.feature", "content": FEATURE}]


def _registry() -> McpToolRegistry:
    contributions = tuple(
        McpToolContribution(tool_id, "software-delivery", factory)
        for tool_id, factory in build_mcp_tools(
            test_file_binding=TestFilePreviewMcpBinding(tags=TAGS)
        )
    )
    return McpToolRegistry(contributions=contributions, enabled_packs=("software-delivery",))


def _caller(*tool_ids: str) -> McpCallerContext:
    return McpCallerContext("ws", "default", frozenset(tool_ids))


def _invoke(arguments: dict[str, object]):  # noqa: ANN202
    return _registry().invoke_authorized(_caller(TOOL_NAME), TOOL_NAME, arguments)


def test_the_test_file_binding_contributes_the_tool_with_its_schemas() -> None:
    tools = dict(build_mcp_tools(test_file_binding=TestFilePreviewMcpBinding(TAGS)))

    tool = tools[TOOL_NAME]()
    assert type(tool) is WriteXrayKeysToFilesTool
    assert tool.args_schema is not None and tool.output_schema is not None


def test_listing_advertises_a_strict_schema() -> None:
    registry = _registry()

    assert registry.list_effective(_caller()) == ()
    [descriptor] = registry.list_effective(_caller(TOOL_NAME))
    assert descriptor.name == mcp_tool_name(TOOL_NAME)
    schema = descriptor.input_schema
    assert sorted(schema["required"]) == ["files", "keys"]
    assert schema["additionalProperties"] is False
    assert descriptor.output_schema is not None


def test_invoke_needs_no_approval_and_returns_structured_content() -> None:
    result = _invoke({"files": FILES, "keys": {"f/a.feature::S": "ABC-9"}})

    assert result.is_error is False
    payload = json.loads(result.text)
    assert payload == result.structured
    [file] = payload["files"]
    assert file["content"] == "Feature: F\n  @XRay:ABC-9\n  Scenario: S\n    Given x\n"
    assert payload["results"][0]["status"] == "TAGGED"


def test_rejections_return_the_trusted_location_and_reason() -> None:
    result = _invoke({"files": FILES, "keys": {"f/a.feature::Missing": "ABC-9"}})

    assert result.structured == {
        "code": VALIDATION_ERROR_CODE,
        "message": f"f/a.feature: {Reason.UNKNOWN_SCENARIO.value}",
    }


@pytest.mark.parametrize(
    "keys",
    [{}, {"f/a.feature::S": "abc-9"}, {"f/a.feature::S": 9}, ["f/a.feature::S"]],
    ids=["empty", "not-an-issue-key", "non-string", "list"],
)
def test_schema_rejects_malformed_keys_with_the_generic_message(keys: object) -> None:
    result = _invoke({"files": FILES, "keys": keys})

    assert result.structured == {"code": VALIDATION_ERROR_CODE, "message": "Invalid tool arguments"}


def test_mcp_wiring_contributes_the_tool_with_configured_tags(monkeypatch) -> None:  # noqa: ANN001
    from composition.mcp.wiring import build_mcp_tool_registry
    from infrastructure.config import load_settings

    for name in ("XRAY_DEPLOYMENT", "XRAY_TEST_TAG", "XRAY_STORY_TAG", "XRAY_MANUAL_TAGS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    monkeypatch.setenv("XRAY_TEST_TAG", "TestKey")

    registry = build_mcp_tool_registry(load_settings(), retrieve=object())  # type: ignore[arg-type]
    result = registry.invoke_authorized(
        _caller(TOOL_NAME), TOOL_NAME, {"files": FILES, "keys": {"f/a.feature::S": "ABC-9"}}
    )

    assert "@TestKey:ABC-9" in json.loads(result.text)["files"][0]["content"]


def test_tool_description_tells_clients_to_send_files_and_apply_the_result() -> None:
    description = WriteXrayKeysToFilesTool(TAGS).description

    for phrase in (".feature", ".robot", "Xray", "exact full text", "path::scenario", "apply"):
        assert phrase in description
