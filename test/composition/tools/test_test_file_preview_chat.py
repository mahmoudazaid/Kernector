"""Chat reachability of software_delivery.preview_test_file_scenarios (#396)."""

from __future__ import annotations

import json

import pytest

from application.contracts import InvokeToolRequest
from application.errors import ApplicationValidationError
from infrastructure.config import load_settings
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.tools.preview_test_file_scenarios import TOOL_NAME

ROBOT = "*** Test Cases ***\nScenario: Login\n    [Tags]    Draft ABC-5\n    Given x\n"
REQUEST = InvokeToolRequest(
    tool_name=TOOL_NAME,
    arguments={"files": [{"path": "tests/login.robot", "content": ROBOT}]},
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in ("XRAY_DEPLOYMENT", "XRAY_TEST_TAG", "XRAY_STORY_TAG", "XRAY_MANUAL_TAGS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    return monkeypatch


def test_registry_lists_the_tool_when_tags_are_supplied(env: pytest.MonkeyPatch) -> None:
    from composition.tools.registry import build_tool_registry

    registry = build_tool_registry(
        load_settings(), test_file_tags=TestFileTagConfig("Draft", "Story", ("manual",))
    )

    assert TOOL_NAME in registry.names()


def test_invoke_tool_runs_the_preview_with_configured_tags(env: pytest.MonkeyPatch) -> None:
    from composition.container import build_invoke_tool

    env.setenv("XRAY_TEST_TAG", "Draft")

    result = build_invoke_tool(load_settings()).execute(REQUEST)

    [scenario] = json.loads(result.result)["files"][0]["scenarios"]
    assert (scenario["summary"], scenario["xray_key"]) == ("Login", "ABC-5")


def test_invoke_tool_rejects_the_tool_when_the_pack_is_disabled(
    env: pytest.MonkeyPatch,
) -> None:
    from composition.container import build_invoke_tool

    env.delenv("DOMAIN_TOOL_PACKS")

    with pytest.raises(ApplicationValidationError, match="Unknown tool name"):
        build_invoke_tool(load_settings()).execute(REQUEST)
