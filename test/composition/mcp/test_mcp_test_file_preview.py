"""MCP exposure of software_delivery.preview_test_file_scenarios (#396).

The tool is a pure parser with no Jira/Xray client, so the ticket's
faked-client criterion has nothing to fake: these tests run with no Xray
binding and no ``XRAY_*`` deployment configured.
"""

from __future__ import annotations

import json

import pytest

from composition.mcp.access import McpCallerContext
from composition.mcp.tool_registry import (
    TOOL_UNAVAILABLE_CODE,
    VALIDATION_ERROR_CODE,
    McpPromptArgumentError,
    McpToolContribution,
    McpToolRegistry,
    mcp_tool_name,
)
from composition.xray_export.test_file_preview import (
    PREVIEW_PROMPT_NAME,
    TestFilePreviewMcpBinding,
)
from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.registration import build_mcp_tools
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.tools.create_xray_tests import TOOL_NAME as CREATE_XRAY_TESTS
from packs.software_delivery.tools.preview_test_file_scenarios import (
    TOOL_NAME,
    PreviewTestFileScenariosTool,
)
from test.composition.mcp.test_mcp_xray_exposure import _Gate, _Importer
from test.composition.mcp.test_mcp_xray_exposure import _registry as _xray_registry

TAGS = TestFileTagConfig("XRay", "Story", ("manual",))
FEATURE = "@ABC-1\nFeature: F\n  @XRay:ABC-2\n  Scenario: S\n    Given x\n"


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


def test_build_mcp_tools_contributes_the_tool_only_with_a_binding() -> None:
    assert build_mcp_tools() == ()

    factories = dict(build_mcp_tools(test_file_binding=TestFilePreviewMcpBinding(TAGS)))

    assert type(factories[TOOL_NAME]()) is PreviewTestFileScenariosTool


def test_listing_is_gated_by_the_allowlist_and_advertises_a_strict_schema() -> None:
    registry = _registry()

    assert registry.list_effective(_caller()) == ()
    [descriptor] = registry.list_effective(_caller(TOOL_NAME))
    assert descriptor.name == mcp_tool_name(TOOL_NAME)
    schema = descriptor.input_schema
    assert schema["required"] == ["files"]
    assert schema["additionalProperties"] is False
    file_schema = schema["$defs"]["TestFileInput"]
    assert file_schema["required"] == ["path", "content"]
    assert file_schema["additionalProperties"] is False
    assert descriptor.output_schema is not None


def test_unauthorized_caller_is_unavailable() -> None:
    result = _registry().invoke_authorized(
        _caller(), TOOL_NAME, {"files": [{"path": "a.feature", "content": FEATURE}]}
    )

    assert result.code == TOOL_UNAVAILABLE_CODE


def test_invoke_needs_no_approval_gate_and_returns_structured_scenarios() -> None:
    result = _invoke({"files": [{"path": "f/a.feature", "content": FEATURE}]})

    assert result.is_error is False
    payload = json.loads(result.text)
    assert payload == result.structured
    [parsed] = payload["files"]
    [scenario] = parsed["scenarios"]
    assert (parsed["story_key"], scenario["xray_key"], payload["scenario_count"]) == (
        "ABC-1",
        "ABC-2",
        1,
    )


def test_doc_strings_pass_output_validation_with_their_indent() -> None:
    content = FEATURE + '      """json\n      {}\n      """\n'

    result = _invoke({"files": [{"path": "f/a.feature", "content": content}]})

    assert result.is_error is False
    [step] = json.loads(result.text)["files"][0]["scenarios"][0]["steps"]
    assert step["doc_string"] == {
        "line": 6,
        "delimiter": '"""',
        "media_type": "json",
        "lines": ["      {}"],
        "indent": 6,
    }


def test_malformed_file_returns_its_sanitized_location_and_reason() -> None:
    result = _invoke({"files": [{"path": "f/a.feature", "content": "Feature: F\n  | a |\n"}]})

    assert result.is_error is True
    assert result.structured == {
        "code": VALIDATION_ERROR_CODE,
        "message": f"f/a.feature:2: {Reason.ORPHAN_TABLE.value}",
    }


def test_long_paths_are_truncated_in_the_message() -> None:
    path = "d/" * 150 + "a.feature"

    result = _invoke({"files": [{"path": path, "content": "Feature: F\n  | a |\n"}]})

    assert result.structured is not None
    message = result.structured["message"]
    assert message.startswith("...") and path not in message
    assert message.endswith(f"a.feature:2: {Reason.ORPHAN_TABLE.value}")


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"files": []}, "Invalid tool arguments"),
        ({"files": [{"path": "a.feature", "content": 1}]}, "Invalid tool arguments"),
        ({"files": [{"path": "a\x00.feature", "content": FEATURE}]}, "Invalid tool arguments"),
        ({"files": [{"path": "a.feature", "content": "  \n"}]}, "File content must not be blank"),
    ],
)
def test_schema_and_untrusted_argument_errors_stay_fixed(
    arguments: dict[str, object], message: str
) -> None:
    result = _invoke(arguments)

    assert result.structured == {"code": VALIDATION_ERROR_CODE, "message": message}


def test_untrusted_tool_validation_errors_keep_the_generic_message() -> None:
    result = _xray_registry(_Importer()).invoke_authorized(
        _caller(CREATE_XRAY_TESTS),
        CREATE_XRAY_TESTS,
        {"draft_id": "other-workspace"},
        approve=_Gate(True),
    )

    assert result.structured == {
        "code": VALIDATION_ERROR_CODE,
        "message": "Invalid tool arguments",
    }


def test_mcp_wiring_contributes_the_tool_without_xray_configured(monkeypatch) -> None:  # noqa: ANN001
    from composition.mcp.wiring import build_mcp_tool_registry
    from infrastructure.config import load_settings

    for name in ("XRAY_DEPLOYMENT", "XRAY_TEST_TAG", "XRAY_STORY_TAG", "XRAY_MANUAL_TAGS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    monkeypatch.setenv("XRAY_TEST_TAG", "TestKey")

    registry = build_mcp_tool_registry(load_settings(), retrieve=object())  # type: ignore[arg-type]
    result = registry.invoke_authorized(
        _caller(TOOL_NAME),
        TOOL_NAME,
        {"files": [{"path": "a.feature", "content": FEATURE.replace("XRay", "TestKey")}]},
    )

    assert [item.name for item in registry.list_effective(_caller(TOOL_NAME))] == [
        mcp_tool_name(TOOL_NAME)
    ]
    assert json.loads(result.text)["files"][0]["scenarios"][0]["xray_key"] == "ABC-2"


def test_tool_description_tells_clients_when_to_use_it_and_to_send_the_file_text() -> None:
    description = PreviewTestFileScenariosTool(TAGS).description

    for phrase in (".feature", ".robot", "Xray", "open in the editor", "exact full text"):
        assert phrase in description


def test_preview_prompt_is_listed_only_for_callers_allowed_the_tool() -> None:
    registry = _registry()

    assert registry.list_prompts(_caller()) == ()
    [prompt] = registry.list_prompts(_caller(TOOL_NAME))
    assert prompt.name == PREVIEW_PROMPT_NAME
    assert prompt.argument == "file"


def test_preview_prompt_renders_the_wire_tool_name_and_the_target_file() -> None:
    registry = _registry()
    caller = _caller(TOOL_NAME)

    named = registry.get_prompt(caller, PREVIEW_PROMPT_NAME, {"file": "features/login.feature"})
    open_file = registry.get_prompt(caller, PREVIEW_PROMPT_NAME, None)

    assert named is not None and open_file is not None
    assert mcp_tool_name(TOOL_NAME) in named
    assert "`features/login.feature`" in named
    assert "open in the editor" in open_file
    assert registry.get_prompt(_caller(), PREVIEW_PROMPT_NAME, None) is None
    assert registry.get_prompt(caller, "unknown", None) is None


@pytest.mark.parametrize("value", ["a\x00.feature", "a" * 513, 1])
def test_preview_prompt_rejects_unsafe_arguments(value: object) -> None:
    with pytest.raises(McpPromptArgumentError):
        _registry().get_prompt(_caller(TOOL_NAME), PREVIEW_PROMPT_NAME, {"file": value})  # type: ignore[dict-item]
