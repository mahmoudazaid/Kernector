"""Chat reachability of software_delivery.write_xray_keys_to_files (#399)."""

from __future__ import annotations

import json

import pytest

from application.contracts import InvokeToolRequest
from application.errors import ApplicationValidationError
from infrastructure.config import load_settings
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.tools.write_xray_keys_to_files import TOOL_NAME

ROBOT = "*** Test Cases ***\nScenario: Login\n    [Tags]    smoke\n    Given x\n"
REQUEST = InvokeToolRequest(
    tool_name=TOOL_NAME,
    arguments={
        "files": [{"path": "tests/login.robot", "content": ROBOT}],
        "keys": {"tests/login.robot::Login": "ABC-9"},
    },
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


def test_invoke_tool_writes_the_configured_marker(env: pytest.MonkeyPatch) -> None:
    from composition.container import build_invoke_tool

    env.setenv("XRAY_TEST_TAG", "Draft")

    result = json.loads(build_invoke_tool(load_settings()).execute(REQUEST).result)

    [written] = result["files"]
    assert "[Tags]    smoke    Draft ABC-9" in written["content"]
    [scenario] = result["results"]
    assert (scenario["key"], scenario["status"]) == ("ABC-9", "TAGGED")


def test_invoke_tool_rejects_the_tool_when_the_pack_is_disabled(
    env: pytest.MonkeyPatch,
) -> None:
    from composition.container import build_invoke_tool

    env.delenv("DOMAIN_TOOL_PACKS")

    with pytest.raises(ApplicationValidationError, match="Unknown tool name"):
        build_invoke_tool(load_settings()).execute(REQUEST)
