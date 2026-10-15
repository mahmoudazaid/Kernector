"""Seam: ``PullXrayTestsToFilesTool.run`` (#400)."""

from __future__ import annotations

import json

import pytest

from domain.test_management.xray import (
    IssueLinkRef,
    IssueLookupResult,
    JiraIssueSummary,
    StoryNamingContext,
    XrayTestDetails,
    XrayTestDetailsResult,
    XrayTestStep,
)
from packs.software_delivery.errors import PullXrayValidationError
from packs.software_delivery.tools.pull_xray_tests_to_files import (
    TOOL_NAME,
    PullXrayTestsToFilesTool,
)


def _story(key: str = "ABC-1", summary: str = "Login story") -> JiraIssueSummary:
    return JiraIssueSummary(key, summary, "10001", "Story", False)


def _test(key: str, summary: str) -> JiraIssueSummary:
    return JiraIssueSummary(key, summary, "10100", "Test", True)


def _link(story: str = "ABC-1") -> IssueLinkRef:
    return IssueLinkRef("Test", "outward", story)


def _manual(
    key: str,
    summary: str,
    action: str = "Open login",
    *,
    links: tuple[IssueLinkRef, ...] | None = None,
) -> XrayTestDetails:
    return XrayTestDetails(
        key=key,
        issue_id=key,
        summary=summary,
        kind="manual",
        steps=(XrayTestStep(action=action, expected="ok"),),
        links=(_link(),) if links is None else links,
    )


class _FakeXray:
    def __init__(
        self,
        *,
        issues: list[JiraIssueSummary] | None = None,
        linked: dict[str, tuple[JiraIssueSummary, ...]] | None = None,
        listed: tuple[JiraIssueSummary, ...] = (),
        details: list[XrayTestDetails] | None = None,
        naming: dict[str, StoryNamingContext] | None = None,
    ) -> None:
        self.issues = {i.key: i for i in (issues or [])}
        self.linked = linked or {}
        self.listed = listed
        self.details = {d.key: d for d in (details or [])}
        self.naming = naming or {}
        self.detail_calls: list[tuple[str, ...]] = []

    def find_issues(self, keys):
        found = {k: self.issues[k] for k in keys if k in self.issues}
        return IssueLookupResult(found=found, missing=frozenset())

    def linked_tests(self, story_key: str):
        return self.linked.get(story_key, ())

    def list_tests(self, project_key: str, *, component: str | None = None):
        return self.listed

    def story_naming_context(self, story_key: str) -> StoryNamingContext:
        if story_key in self.naming:
            return self.naming[story_key]
        return StoryNamingContext(story_key, self.issues[story_key].summary, "absent")

    def test_details(self, keys):
        self.detail_calls.append(tuple(keys))
        found = {k: self.details[k] for k in keys if k in self.details}
        return XrayTestDetailsResult(found=found, unreadable=frozenset())

    def capabilities(self):
        raise AssertionError("unused")

    def update_test(self, patch):
        raise AssertionError("unused")


def _tool(xray: _FakeXray, **kw) -> PullXrayTestsToFilesTool:
    return PullXrayTestsToFilesTool(
        lookup=xray,
        updater=xray,
        tags=__import__(
            "packs.software_delivery.test_files.models", fromlist=["TestFileTagConfig"]
        ).TestFileTagConfig("XRay", "Story", ("manual", "scaffold")),
        project_key="QA",
        story_issue_types=frozenset({"Story"}),
        link_type="Test",
        link_direction="outward",
        default_component="Portal",
        **kw,
    )


def _run(xray: _FakeXray, **arguments) -> dict:
    return json.loads(_tool(xray).run(arguments))


def test_tool_name_and_story_scope_adds_new_robot_file() -> None:
    xray = _FakeXray(
        issues=[_story()],
        linked={"ABC-1": (_test("QA-7", "User logs in"),)},
        details=[_manual("QA-7", "User logs in")],
        naming={"ABC-1": StoryNamingContext("ABC-1", "Login story", "absent")},
    )

    payload = _run(xray, story_key="ABC-1", files=[], dry_run=False)

    assert _tool(xray).name == TOOL_NAME
    assert payload["scope"] == {"kind": "story", "story_key": "ABC-1"}
    assert payload["results"][0]["status"] == "NEW_FILE"
    assert payload["files"]
    assert "*** Test Cases ***" in payload["files"][0]["content"]
    assert "XRay:QA-7" in payload["files"][0]["content"]


def test_dry_run_same_resolution_without_file_content() -> None:
    xray = _FakeXray(
        issues=[_story()],
        linked={"ABC-1": (_test("QA-7", "User logs in"),)},
        details=[_manual("QA-7", "User logs in")],
        naming={"ABC-1": StoryNamingContext("ABC-1", "Login story", "absent")},
    )

    payload = _run(xray, story_key="ABC-1", files=[], dry_run=True)

    assert payload["dry_run"] is True
    assert payload["results"][0]["status"] == "WOULD_NEW_FILE"
    assert payload["files"] == []


def test_known_key_skipped_globally_before_details() -> None:
    robot = (
        "*** Settings ***\nDefault Tags    Story    ABC-1\n\n"
        "*** Test Cases ***\nScenario: User logs in\n    [Tags]    XRay:QA-7\n"
        "    Given already here\n"
    )
    xray = _FakeXray(
        issues=[_story()],
        linked={"ABC-1": (_test("QA-7", "User logs in"),)},
        details=[_manual("QA-7", "User logs in")],
    )

    payload = _run(
        xray,
        story_key="ABC-1",
        files=[{"path": "t.robot", "content": robot}],
        formats=["robot", "feature"],
    )

    assert {r["status"] for r in payload["results"]} == {"SKIP_KNOWN"}
    assert xray.detail_calls == []


def test_component_rejected_on_story_scope() -> None:
    with pytest.raises(PullXrayValidationError, match="component_on_story_scope"):
        _tool(_FakeXray(issues=[_story()])).run(
            {"story_key": "ABC-1", "component": "Portal", "files": []}
        )


def test_project_omitted_component_uses_default() -> None:
    xray = _FakeXray(
        issues=[_story()],
        listed=(_test("QA-7", "User logs in"),),
        details=[_manual("QA-7", "User logs in")],
        naming={"ABC-1": StoryNamingContext("ABC-1", "Login story", "absent")},
    )

    payload = _run(xray, project=True, files=[], dry_run=True)

    assert payload["scope"]["component"] == "Portal"
    assert payload["results"][0]["status"] == "WOULD_NEW_FILE"


def test_project_explicit_null_component_disables_default() -> None:
    xray = _FakeXray(listed=(), issues=[])

    payload = _run(xray, project=True, component=None, files=[])

    assert payload["scope"]["component"] is None
    assert payload["results"] == []


def test_skip_no_story_when_links_absent() -> None:
    detail = _manual("QA-7", "User logs in", links=())
    xray = _FakeXray(
        issues=[_story()],
        linked={"ABC-1": (_test("QA-7", "User logs in"),)},
        details=[detail],
    )

    payload = _run(xray, story_key="ABC-1", files=[], dry_run=True)

    assert payload["results"][0]["status"] == "STORY_LINK_UNCONFIRMED"


def test_backfill_untagged_same_summary() -> None:
    robot = (
        "*** Settings ***\nDefault Tags    Story    ABC-1\n\n"
        "*** Test Cases ***\nScenario: User logs in\n    [Tags]    manual\n    Given old\n"
    )
    xray = _FakeXray(
        issues=[_story()],
        linked={"ABC-1": (_test("QA-7", "User logs in"),)},
        details=[_manual("QA-7", "User logs in")],
    )

    payload = _run(
        xray,
        story_key="ABC-1",
        files=[{"path": "t.robot", "content": robot}],
        dry_run=False,
    )

    assert payload["results"][0]["status"] == "BACKFILL_TAG"
    assert "QA-7" in payload["files"][0]["content"]
    assert "Given old" in payload["files"][0]["content"]


def test_idempotent_when_proposed_text_resupplied() -> None:
    xray = _FakeXray(
        issues=[_story()],
        linked={"ABC-1": (_test("QA-7", "User logs in"),)},
        details=[_manual("QA-7", "User logs in")],
        naming={"ABC-1": StoryNamingContext("ABC-1", "Login story", "absent")},
    )
    first = _run(xray, story_key="ABC-1", files=[], dry_run=False)
    path = first["files"][0]["path"]
    content = first["files"][0]["content"]

    second = _run(
        xray,
        story_key="ABC-1",
        files=[{"path": path, "content": content}],
        dry_run=False,
    )

    assert second["results"][0]["status"] == "SKIP_KNOWN"
    assert second["files"] == []


def test_existing_story_file_gets_add_not_new_file() -> None:
    robot = (
        "*** Settings ***\nDefault Tags    Story    ABC-1\n\n"
        "*** Test Cases ***\nScenario: Other case\n    [Tags]    manual\n"
        "    Given keep me\n"
    )
    xray = _FakeXray(
        issues=[_story()],
        linked={"ABC-1": (_test("QA-7", "User logs in"),)},
        details=[_manual("QA-7", "User logs in")],
        naming={"ABC-1": StoryNamingContext("ABC-1", "Login story", "absent")},
    )

    payload = _run(
        xray,
        story_key="ABC-1",
        files=[{"path": "suites/login.robot", "content": robot}],
        new_file_paths={"ABC-1": "ignored_new.robot"},
        dry_run=False,
    )

    assert payload["results"][0]["status"] == "ADD"
    assert payload["results"][0]["path"] == "suites/login.robot"
    assert payload["files"][0]["path"] == "suites/login.robot"
    assert "User logs in" in payload["files"][0]["content"]
    assert "Given keep me" in payload["files"][0]["content"]


def test_new_file_paths_override_suggested_basename() -> None:
    xray = _FakeXray(
        issues=[_story()],
        linked={"ABC-1": (_test("QA-7", "User logs in"),)},
        details=[_manual("QA-7", "User logs in")],
        naming={"ABC-1": StoryNamingContext("ABC-1", "Login story", "absent")},
    )

    payload = _run(
        xray,
        story_key="ABC-1",
        files=[],
        new_file_paths={"ABC-1": "custom/login_suite"},
        dry_run=False,
    )

    assert payload["results"][0]["status"] == "NEW_FILE"
    assert payload["results"][0]["path"] == "custom/login_suite.robot"
    assert payload["files"][0]["path"] == "custom/login_suite.robot"


@pytest.mark.parametrize("overrides", [None, {"ABC-1": "tests/login"}])
def test_several_tests_of_one_story_share_a_new_file(overrides) -> None:
    keys = ("QA-1", "QA-2", "QA-3")
    xray = _FakeXray(
        issues=[_story()],
        linked={"ABC-1": tuple(_test(k, f"Case {k}") for k in keys)},
        details=[_manual(k, f"Case {k}") for k in keys],
        naming={"ABC-1": StoryNamingContext("ABC-1", "Login story", "absent")},
    )
    arguments: dict[str, object] = {"story_key": "ABC-1", "files": [], "formats": ["robot", "feature"]}
    if overrides is not None:
        arguments["new_file_paths"] = overrides

    payload = _run(xray, **arguments)

    assert {r["status"] for r in payload["results"]} == {"NEW_FILE"}
    assert len(payload["files"]) == 2
    for file in payload["files"]:
        assert all(f"XRay:{k}" in file["content"] for k in keys)


def test_new_path_claimed_by_other_story_collides() -> None:
    xray = _FakeXray(
        issues=[_story("ABC-1"), _story("ABC-2")],
        listed=(_test("QA-1", "One"), _test("QA-2", "Two")),
        details=[
            _manual("QA-1", "One"),
            _manual("QA-2", "Two", links=(_link("ABC-2"),)),
        ],
        naming={
            "ABC-1": StoryNamingContext("ABC-1", "Same", "absent"),
            "ABC-2": StoryNamingContext("ABC-2", "Same", "absent"),
        },
    )

    payload = _run(xray, project=True, files=[])

    assert [r["status"] for r in payload["results"]] == ["NEW_FILE", "PATH_COLLISION"]


def test_add_to_suite_matched_by_scenario_tag_keeps_story() -> None:
    from packs.software_delivery.test_files.models import TestFileTagConfig
    from packs.software_delivery.test_files.parser import parse_test_file

    robot = (
        "*** Test Cases ***\nScenario: Existing\n"
        "    [Tags]    Story ABC-1    XRay QA-1\n    Given x\n"
    )
    xray = _FakeXray(
        issues=[_story()],
        linked={"ABC-1": (_test("QA-2", "New one"),)},
        details=[_manual("QA-2", "New one")],
    )

    payload = _run(xray, story_key="ABC-1", files=[{"path": "s.robot", "content": robot}])

    assert payload["results"][0]["status"] == "ADD"
    reparsed = parse_test_file(
        "s.robot", payload["files"][0]["content"], TestFileTagConfig("XRay", "Story", ("manual", "scaffold"))
    )
    added = next(s for s in reparsed.scenarios if s.summary == "New one")
    assert (added.xray_key, added.story_key) == ("QA-2", "ABC-1")


def test_duplicate_remote_link_is_not_ambiguous() -> None:
    xray = _FakeXray(
        issues=[_story()],
        linked={"ABC-1": (_test("QA-2", "Dup"), _test("QA-2", "Dup"))},
        details=[_manual("QA-2", "Dup")],
        naming={"ABC-1": StoryNamingContext("ABC-1", "Login story", "absent")},
    )

    payload = _run(xray, story_key="ABC-1", files=[], dry_run=True)

    assert [r["status"] for r in payload["results"]] == ["WOULD_NEW_FILE"]


def test_new_file_name_template_override() -> None:
    xray = _FakeXray(
        issues=[_story()],
        linked={"ABC-1": (_test("QA-7", "User logs in"),)},
        details=[_manual("QA-7", "User logs in")],
        naming={"ABC-1": StoryNamingContext("ABC-1", "Login story", "absent")},
    )

    payload = _run(
        xray,
        story_key="ABC-1",
        files=[],
        new_file_name_template="{story_key}_suite",
        dry_run=True,
    )

    assert payload["results"][0]["status"] == "WOULD_NEW_FILE"
    assert payload["results"][0]["path"] == "ABC-1_suite.robot"


def test_approval_hints_list_scope_inventory_and_overrides() -> None:
    from domain.tool_approval import ToolApprovalPolicy

    robot = (
        "*** Settings ***\nDefault Tags    Story    ABC-1\n\n"
        "*** Test Cases ***\nScenario: Other\n    Given x\n"
    )
    tool = _tool(_FakeXray(), destination_label="Jira project QA")

    hints = tool.approval_hints(
        {
            "story_key": "ABC-1",
            "files": [{"path": "suites/login.robot", "content": robot}],
            "new_file_paths": {"ABC-2": "other.robot"},
        }
    )

    assert ToolApprovalPolicy().requires_approval(TOOL_NAME) is True
    assert hints.title == "Pull Xray tests into files"
    assert hints.destination_label == "Jira project QA"
    assert "story · ABC-1" in hints.item_titles
    assert "existing · login.robot" in hints.item_titles
    assert "new · ABC-2 → other.robot" in hints.item_titles
    dry = tool.approval_hints({"story_key": "ABC-1", "files": [], "dry_run": True})
    assert dry.title == "Preview pull of Xray tests into files"
