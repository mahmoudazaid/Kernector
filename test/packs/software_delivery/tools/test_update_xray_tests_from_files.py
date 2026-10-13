"""Seam: ``UpdateXrayTestsFromFilesTool.run`` with a fake Jira/Xray lookup and updater (#398)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace

import pytest

from domain.errors import ConnectorAuthError, ConnectorUnavailableError, ToolFailureError
from domain.test_management.xray import (
    CucumberDefinition,
    IssueLinkRef,
    IssueLookupResult,
    JiraIssueSummary,
    ManualDefinition,
    XrayTestDetails,
    XrayTestDetailsResult,
    XrayTestPatch,
    XrayTestStep,
    XrayUpdateCapabilities,
    XrayUpdateNotConfirmedError,
    XrayUpdateRejectedError,
    XrayUpdateUncertainError,
)
from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.tools.update_xray_tests_from_files import (
    TOOL_NAME,
    UpdateXrayTestsFromFilesTool,
)

TAGS = TestFileTagConfig(test_marker="XRay", story_marker="Story", manual_tags=("manual",))
STORY_TYPES = frozenset({"Story"})
LINK_TYPE = "Test"
EDITABLE = frozenset(
    {"summary", "test_type", "steps", "gherkin", "scenario_type", "component", "story_link"}
)


def _story(key: str) -> JiraIssueSummary:
    return JiraIssueSummary(key, f"Story {key}", "10001", "Story", False)


def _test(key: str, summary: str = "Some test") -> JiraIssueSummary:
    return JiraIssueSummary(key, summary, "10002", "Test", True)


def _link(story: str = "ABC-1") -> IssueLinkRef:
    return IssueLinkRef(LINK_TYPE, "outward", story)


def _manual(
    key: str,
    summary: str,
    *steps: str,
    links: tuple[IssueLinkRef, ...] = (),
    **values: object,
) -> XrayTestDetails:
    return XrayTestDetails(
        key=key,
        issue_id=f"id-{key}",
        summary=summary,
        kind="manual",
        project_key="QA",
        steps=tuple(XrayTestStep(action=step) for step in steps),
        links=links,
        editable=EDITABLE,
        **values,  # type: ignore[arg-type]
    )


def _cucumber(
    key: str,
    summary: str,
    gherkin: str,
    *,
    outline: bool = False,
    links: tuple[IssueLinkRef, ...] = (),
    **values: object,
) -> XrayTestDetails:
    return XrayTestDetails(
        key=key,
        issue_id=f"id-{key}",
        summary=summary,
        kind="cucumber",
        project_key="QA",
        scenario_type="scenario_outline" if outline else "scenario",
        gherkin=gherkin,
        links=links,
        editable=EDITABLE,
        **values,  # type: ignore[arg-type]
    )


class _FakeXray:
    """Fake lookup + updater; records every call and replays scripted update outcomes."""

    def __init__(
        self,
        *,
        issues: Sequence[JiraIssueSummary] = (),
        missing: Sequence[str] = (),
        linked: dict[str, tuple[JiraIssueSummary, ...]] | None = None,
        details: Sequence[XrayTestDetails] = (),
        unreadable: Sequence[str] = (),
        capabilities: XrayUpdateCapabilities | None = None,
        outcomes: Sequence[object] = (),
    ) -> None:
        self.issues = {issue.key: issue for issue in issues}
        self.missing = frozenset(missing)
        self.linked = linked or {}
        self.details = {item.key: item for item in details}
        self.unreadable = frozenset(unreadable)
        self.capabilities_value = capabilities or XrayUpdateCapabilities(
            jira_fields=True, story_link_type=True
        )
        self.outcomes = list(outcomes)
        self.lookups: list[tuple[str, ...]] = []
        self.linked_calls: list[str] = []
        self.detail_calls: list[tuple[str, ...]] = []
        self.patches: list[XrayTestPatch] = []

    def find_issues(self, keys: Sequence[str]) -> IssueLookupResult:
        self.lookups.append(tuple(keys))
        return IssueLookupResult(
            found={k: self.issues[k] for k in keys if k in self.issues},
            missing=frozenset(k for k in keys if k in self.missing),
        )

    def linked_tests(self, story_key: str) -> tuple[JiraIssueSummary, ...]:
        self.linked_calls.append(story_key)
        return self.linked.get(story_key, ())

    def capabilities(self) -> XrayUpdateCapabilities:
        return self.capabilities_value

    def test_details(self, keys: Sequence[str]) -> XrayTestDetailsResult:
        self.detail_calls.append(tuple(keys))
        return XrayTestDetailsResult(
            found={k: self.details[k] for k in keys if k in self.details},
            unreadable=frozenset(k for k in keys if k in self.unreadable),
        )

    def update_test(self, patch: XrayTestPatch) -> None:
        self.patches.append(patch)
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, Exception):
            raise outcome


def _tool(xray: _FakeXray, *, component: str | None = None) -> UpdateXrayTestsFromFilesTool:
    return UpdateXrayTestsFromFilesTool(
        lookup=xray,
        updater=xray,
        tags=TAGS,
        project_key="QA",
        story_issue_types=STORY_TYPES,
        link_type=LINK_TYPE,
        default_component=component,
        destination_label="QA",
    )


def _run(xray: _FakeXray, *files: tuple[str, str], dry_run: bool | None = None, **kw) -> dict:
    arguments: dict[str, object] = {
        "files": [{"path": path, "content": content} for path, content in files]
    }
    if dry_run is not None:
        arguments["dry_run"] = dry_run
    return json.loads(_tool(xray, **kw).run(arguments))


def _lines(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _tagged_robot(tags: str = "XRay QA-7    Story ABC-1", name: str = "User logs in") -> str:
    return _lines(
        "*** Test Cases ***",
        f"Scenario: {name}",
        f"    [Tags]    manual    {tags}",
        "    Given the login page",
    )


def test_unchanged_tagged_test_is_skipped_without_any_write() -> None:
    xray = _FakeXray(
        issues=[_test("QA-7", "User logs in"), _story("ABC-1")],
        details=[_manual("QA-7", "User logs in", "Given the login page", links=(_link(),))],
    )

    payload = _run(xray, ("t.robot", _tagged_robot()))

    assert _tool(xray).name == TOOL_NAME == "software_delivery.update_xray_tests_from_files"
    assert payload["results"] == [
        {
            "path": "t.robot",
            "line": 2,
            "summary": "User logs in",
            "status": "SKIPPED",
            "key": "QA-7",
            "candidate_keys": [],
            "story_key": "ABC-1",
            "story_problem": None,
            "changes": [],
            "reason": None,
        }
    ]
    assert xray.patches == []
    assert xray.detail_calls == [("QA-7",)]
    assert payload["counts"] == {"UPDATED": 0, "WOULD_UPDATE": 0, "SKIPPED": 1, "ERROR": 0}


def test_renamed_tagged_test_gets_only_its_summary_updated() -> None:
    xray = _FakeXray(
        issues=[_test("QA-7", "Old name"), _story("ABC-1")],
        details=[_manual("QA-7", "Old name", "Given the login page", links=(_link(),))],
    )

    planned = _run(xray, ("t.robot", _tagged_robot()), dry_run=True)

    [result] = planned["results"]
    assert (result["status"], result["changes"]) == ("WOULD_UPDATE", ["summary"])
    assert xray.patches == []

    payload = _run(xray, ("t.robot", _tagged_robot()))

    [result] = payload["results"]
    assert (result["status"], result["changes"]) == ("UPDATED", ["summary"])
    [patch] = xray.patches
    assert patch == XrayTestPatch(key="QA-7", issue_id="id-QA-7", summary="User logs in")
    assert payload["dry_run"] is False


@pytest.mark.parametrize(
    "existing",
    [
        IssueLinkRef("Relates", "outward", "ABC-1"),
        IssueLinkRef(LINK_TYPE, "inward", "ABC-1"),
        IssueLinkRef(LINK_TYPE, "outward", "ABC-2"),
    ],
    ids=["wrong-type", "wrong-direction", "other-story"],
)
def test_tagged_test_without_the_required_story_link_gets_only_the_link_added(
    existing: IssueLinkRef,
) -> None:
    xray = _FakeXray(
        issues=[_test("QA-7", "User logs in"), _story("ABC-1")],
        details=[_manual("QA-7", "User logs in", "Given the login page", links=(existing,))],
    )

    payload = _run(xray, ("t.robot", _tagged_robot()))

    [result] = payload["results"]
    assert (result["status"], result["changes"]) == ("UPDATED", ["story_link"])
    [patch] = xray.patches
    assert patch == XrayTestPatch(key="QA-7", issue_id="id-QA-7", add_story_link=_link())


def test_bare_test_key_match_resolves_the_story_from_the_other_bare_key() -> None:
    xray = _FakeXray(
        issues=[_test("QA-7", "User logs in"), _story("ABC-1")],
        details=[_manual("QA-7", "User logs in", "Given the login page")],
    )

    payload = _run(xray, ("t.robot", _tagged_robot("QA-7    ABC-1")))

    [result] = payload["results"]
    assert (result["status"], result["key"], result["story_key"]) == ("UPDATED", "QA-7", "ABC-1")
    assert result["changes"] == ["story_link"]
    assert xray.patches[0].add_story_link == _link()


FEATURE_STORY = _lines(
    "@ABC-1",
    "Feature: Login",
    "",
    "  {tag}",
    "  Scenario: User logs in",
    "    Given the login page",
)


@pytest.mark.parametrize("tag", ["@XRay:QA-7", "@QA-7"], ids=["tagged", "bare"])
def test_feature_match_uses_the_feature_level_story_for_the_link(tag: str) -> None:
    xray = _FakeXray(
        issues=[_test("QA-7", "User logs in"), _story("ABC-1")],
        details=[_cucumber("QA-7", "User logs in", "Given the login page")],
    )

    payload = _run(xray, ("f/login.feature", FEATURE_STORY.format(tag=tag)))

    [result] = payload["results"]
    assert (result["status"], result["story_key"], result["changes"]) == (
        "UPDATED",
        "ABC-1",
        ["story_link"],
    )


def test_explicit_match_without_a_story_still_updates_its_other_fields() -> None:
    xray = _FakeXray(
        issues=[_test("QA-7", "Old name")],
        details=[_manual("QA-7", "Old name", "Given the login page")],
    )

    payload = _run(xray, ("t.robot", _tagged_robot("XRay QA-7")))

    [result] = payload["results"]
    assert (result["status"], result["changes"]) == ("UPDATED", ["summary"])
    assert (result["story_key"], result["story_problem"]) == (None, "no_story")
    assert xray.patches[0].add_story_link is None


def _error(result: dict) -> tuple[str, str | None]:
    return result["status"], result["reason"]


@pytest.mark.parametrize(
    ("issues", "missing", "reason"),
    [
        ([_test("QA-8", "User logs in")], ["QA-7"], "issue_not_found"),
        ([_test("QA-8", "User logs in")], [], "issue_unresolved"),
        ([_story("QA-7"), _test("QA-8", "User logs in")], [], "not_a_test"),
    ],
    ids=["missing", "unresolved", "not-a-test"],
)
def test_invalid_tag_is_an_error_with_no_fallback(
    issues: list[JiraIssueSummary], missing: list[str], reason: str
) -> None:
    xray = _FakeXray(
        issues=[*issues, _story("ABC-1")],
        missing=missing,
        linked={"ABC-1": (_test("QA-9", "User logs in"),)},
        details=[_manual("QA-8", "x"), _manual("QA-9", "x")],
    )

    payload = _run(xray, ("t.robot", _tagged_robot("XRay QA-7    QA-8    Story ABC-1")))

    [result] = payload["results"]
    assert _error(result) == ("ERROR", reason)
    assert result["key"] == "QA-7"
    assert (xray.linked_calls, xray.detail_calls, xray.patches) == ([], [], [])


@pytest.mark.parametrize(
    ("issues", "missing", "reason"),
    [([], ["QA-8"], "issue_not_found"), ([], [], "issue_unresolved")],
    ids=["missing", "unresolved"],
)
def test_invalid_bare_key_is_an_error_with_no_summary_fallback(
    issues: list[JiraIssueSummary], missing: list[str], reason: str
) -> None:
    xray = _FakeXray(
        issues=[*issues, _story("ABC-1")],
        missing=missing,
        linked={"ABC-1": (_test("QA-9", "User logs in"),)},
    )

    payload = _run(xray, ("t.robot", _tagged_robot("QA-8    Story ABC-1")))

    [result] = payload["results"]
    assert _error(result) == ("ERROR", reason)
    assert (xray.linked_calls, xray.patches) == ([], [])


def test_two_bare_test_keys_are_ambiguous() -> None:
    xray = _FakeXray(issues=[_test("QA-7"), _test("QA-8"), _story("ABC-1")])

    payload = _run(xray, ("t.robot", _tagged_robot("QA-7    QA-8    Story ABC-1")))

    [result] = payload["results"]
    assert _error(result) == ("ERROR", "ambiguous")
    assert result["candidate_keys"] == ["QA-7", "QA-8"]


@pytest.mark.parametrize(
    "other_tags", ["XRay QA-7    Story ABC-1", "QA-7    Story ABC-1"], ids=["tag", "bare"]
)
def test_key_claimed_by_two_scenarios_is_an_error_for_both_and_never_written(
    other_tags: str,
) -> None:
    xray = _FakeXray(
        issues=[_test("QA-7", "Old"), _story("ABC-1")],
        details=[_manual("QA-7", "Old", "Given the login page")],
    )

    payload = _run(
        xray,
        ("a.robot", _tagged_robot()),
        ("b.robot", _tagged_robot(other_tags, name="Someone logs in")),
    )

    assert [_error(r) for r in payload["results"]] == [("ERROR", "test_key_claimed")] * 2
    assert [r["key"] for r in payload["results"]] == ["QA-7", "QA-7"]
    assert xray.patches == []


def test_untagged_scenario_matches_the_story_test_with_the_same_summary() -> None:
    xray = _FakeXray(
        issues=[_story("ABC-1")],
        linked={"ABC-1": (_test("QA-5", "Other"), _test("QA-7", "User logs in"))},
        details=[_manual("QA-7", "User logs in", "Given the login page", links=(_link(),))],
    )

    payload = _run(xray, ("t.robot", _tagged_robot("Story ABC-1")))

    [result] = payload["results"]
    assert (result["status"], result["key"], result["story_key"]) == ("SKIPPED", "QA-7", "ABC-1")


@pytest.mark.parametrize(
    ("linked", "reason", "candidates"),
    [
        ((), "not_found", []),
        ((_test("QA-5", "User logs in "),), "not_found", []),
        ((_test("QA-5", "User logs in"), _test("QA-6", "User logs in")), "ambiguous", ["QA-5", "QA-6"]),
    ],
    ids=["none", "inexact", "several"],
)
def test_summary_match_outcomes(
    linked: tuple[JiraIssueSummary, ...], reason: str, candidates: list[str]
) -> None:
    xray = _FakeXray(issues=[_story("ABC-1")], linked={"ABC-1": linked})

    payload = _run(xray, ("t.robot", _tagged_robot("Story ABC-1")))

    [result] = payload["results"]
    assert _error(result) == ("ERROR", reason)
    assert result["candidate_keys"] == candidates
    assert xray.detail_calls == []


def test_summary_match_skips_explicitly_claimed_keys() -> None:
    xray = _FakeXray(
        issues=[_test("QA-5", "User logs in"), _story("ABC-1")],
        linked={"ABC-1": (_test("QA-5", "User logs in"),)},
        details=[_manual("QA-5", "User logs in", "Given the login page", links=(_link(),))],
    )

    payload = _run(
        xray,
        ("a.robot", _tagged_robot("XRay QA-5    Story ABC-1")),
        ("b.robot", _tagged_robot("Story ABC-1")),
    )

    tagged, untagged = payload["results"]
    assert tagged["status"] == "SKIPPED"
    assert _error(untagged) == ("ERROR", "test_key_claimed")
    assert untagged["candidate_keys"] == ["QA-5"]


def test_repeated_summary_match_in_the_run_is_claimed_not_skipped() -> None:
    xray = _FakeXray(
        issues=[_story("ABC-1")],
        linked={"ABC-1": (_test("QA-5", "User logs in"),)},
        details=[_manual("QA-5", "User logs in", "Given the login page", links=(_link(),))],
    )
    text = _tagged_robot("Story ABC-1")

    first, second = _run(xray, ("a.robot", text), ("b.robot", text))["results"]

    assert (first["status"], first["key"]) == ("SKIPPED", "QA-5")
    assert _error(second) == ("ERROR", "test_key_claimed")


@pytest.mark.parametrize(
    ("tags", "missing", "reason"),
    [("smoke", [], "no_story"), ("Story ABC-9", ["ABC-9"], "story_not_found")],
    ids=["no-story", "story-not-found"],
)
def test_summary_match_needs_a_valid_story(tags: str, missing: list[str], reason: str) -> None:
    xray = _FakeXray(issues=[], missing=missing)

    payload = _run(xray, ("t.robot", _tagged_robot(tags)))

    [result] = payload["results"]
    assert _error(result) == ("ERROR", reason)
    assert xray.linked_calls == []


def test_duplicate_scenario_names_are_rejected_before_any_jira_call_even_when_tagged() -> None:
    xray = _FakeXray()
    twice = _lines(
        "*** Test Cases ***",
        "Scenario: Login",
        "    [Tags]    XRay QA-7",
        "    Given a",
        "Scenario: Login",
        "    [Tags]    XRay QA-8",
        "    Given b",
    )

    with pytest.raises(TestFileValidationError) as error:
        _run(xray, ("t.robot", twice))

    assert (error.value.reason, error.value.line) == (Reason.DUPLICATE_SCENARIO_NAME, 5)
    assert xray.lookups == []


def test_explicit_match_with_a_non_story_parent_reports_the_problem_and_skips_the_link() -> None:
    bug = JiraIssueSummary("ABC-1", "A bug", "10003", "Bug", False)
    xray = _FakeXray(
        issues=[_test("QA-7", "User logs in"), bug],
        details=[_manual("QA-7", "User logs in", "Given the login page")],
    )

    payload = _run(xray, ("t.robot", _tagged_robot()))

    [result] = payload["results"]
    assert (result["status"], result["story_problem"]) == ("SKIPPED", "not_a_story")
    assert xray.patches == []


OUTLINE = _lines(
    "@ABC-1",
    "Feature: Login",
    "",
    "  @XRay:QA-7",
    "  Scenario Outline: User logs in",
    "    Given the user <name>",
    "",
    "    Examples:",
    "      | name |",
    "      | ann  |",
)
OUTLINE_GHERKIN = "Given the user <name>\n\nExamples:\n  | name |\n  | ann |"
SCENARIO = FEATURE_STORY.format(tag="@XRay:QA-7")


def _single(xray: _FakeXray, path: str, text: str, **kw: object) -> tuple[dict, XrayTestPatch | None]:
    payload = _run(xray, (path, text), **kw)
    [result] = payload["results"]
    return result, (xray.patches[0] if xray.patches else None)


def test_outline_only_change_updates_the_scenario_type_without_a_kind_change() -> None:
    xray = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")],
        details=[_cucumber("QA-7", "User logs in", OUTLINE_GHERKIN, links=(_link(),))],
    )

    result, patch = _single(xray, "f.feature", OUTLINE)

    assert result["changes"] == ["scenario_type", "gherkin"]
    assert patch == XrayTestPatch(
        key="QA-7",
        issue_id="id-QA-7",
        scenario_type_change=("scenario", "scenario_outline"),
        definition=CucumberDefinition(OUTLINE_GHERKIN, outline=True),
    )


def test_manual_test_switched_to_cucumber_carries_the_complete_gherkin() -> None:
    xray = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")],
        details=[_manual("QA-7", "User logs in", "Given the login page", links=(_link(),))],
    )

    result, patch = _single(xray, "f.feature", SCENARIO)

    assert result["changes"] == ["test_type", "gherkin"]
    assert patch == XrayTestPatch(
        key="QA-7",
        issue_id="id-QA-7",
        kind_change=("manual", "cucumber"),
        definition=CucumberDefinition("Given the login page"),
    )


def test_cucumber_test_switched_to_manual_carries_the_complete_steps() -> None:
    xray = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")],
        details=[_cucumber("QA-7", "User logs in", "Given the login page", links=(_link(),))],
    )

    result, patch = _single(xray, "t.robot", _tagged_robot())

    assert result["changes"] == ["test_type", "steps"]
    assert patch is not None
    assert patch.kind_change == ("cucumber", "manual")
    assert patch.definition == ManualDefinition((XrayTestStep(action="Given the login page"),))


@pytest.mark.parametrize(
    "existing",
    [
        (XrayTestStep(action="Given another page", data="admin"),),
        (XrayTestStep(action="Given the login page"), XrayTestStep(action="Then more")),
    ],
    ids=["action", "count"],
)
def test_steps_only_change_sends_only_the_steps(existing: tuple[XrayTestStep, ...]) -> None:
    details = _manual("QA-7", "User logs in", links=(_link(),))
    xray = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")],
        details=[replace(details, steps=existing)],
    )

    result, patch = _single(xray, "t.robot", _tagged_robot())

    assert result["changes"] == ["steps"]
    assert patch == XrayTestPatch(
        key="QA-7",
        issue_id="id-QA-7",
        definition=ManualDefinition((XrayTestStep(action="Given the login page"),)),
    )


def test_existing_step_data_alone_is_not_a_change() -> None:
    details = _manual("QA-7", "User logs in", links=(_link(),))
    xray = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")],
        details=[
            replace(details, steps=(XrayTestStep(action="Given the login page", data="admin"),))
        ],
    )

    result, patch = _single(xray, "t.robot", _tagged_robot())

    assert (result["status"], patch) == ("SKIPPED", None)


def test_rewritten_steps_keep_the_data_of_unchanged_steps() -> None:
    details = _manual("QA-7", "User logs in", links=(_link(),))
    existing = (
        XrayTestStep(action="Given the login page", data="admin"),
        XrayTestStep(action="When the old step", data="stale"),
    )
    xray = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")], details=[replace(details, steps=existing)]
    )
    robot = _lines(
        "*** Test Cases ***",
        "Scenario: User logs in",
        "    [Tags]    manual    XRay QA-7    Story ABC-1",
        "    Given the login page",
        "    When the new step",
    )

    result, patch = _single(xray, "t.robot", robot)

    assert result["changes"] == ["steps"]
    assert patch is not None
    assert patch.definition == ManualDefinition(
        (
            XrayTestStep(action="Given the login page", data="admin"),
            XrayTestStep(action="When the new step"),
        )
    )


def test_test_outside_the_configured_project_is_an_error_before_any_write() -> None:
    details = _manual("OTHER-5", "Old name", "Given another page", links=(_link(),))
    xray = _FakeXray(
        issues=[_test("OTHER-5"), _story("ABC-1")],
        details=[replace(details, project_key="OTHER")],
    )

    payload = _run(xray, ("t.robot", _tagged_robot("XRay OTHER-5    Story ABC-1")))

    [result] = payload["results"]
    assert _error(result) == ("ERROR", "other_project")
    assert result["changes"] == []
    assert xray.patches == []


def test_gherkin_only_change_sends_only_the_gherkin_and_ignores_line_endings() -> None:
    changed = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")],
        details=[_cucumber("QA-7", "User logs in", "Given another page", links=(_link(),))],
    )
    same = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")],
        details=[_cucumber("QA-7", "User logs in", "Given the login page  \r\n", links=(_link(),))],
    )

    result, patch = _single(changed, "f.feature", SCENARIO)
    unchanged, _ = _single(same, "f.feature", SCENARIO)

    assert result["changes"] == ["gherkin"]
    assert patch == XrayTestPatch(
        key="QA-7", issue_id="id-QA-7", definition=CucumberDefinition("Given the login page")
    )
    assert unchanged["status"] == "SKIPPED"


@pytest.mark.parametrize(
    ("components", "expected"),
    [((), "Web"), (("Api",), "Web"), (("Api", "Web"), None)],
    ids=["none", "other", "present"],
)
def test_default_component_is_added_when_missing_and_others_are_kept(
    components: tuple[str, ...], expected: str | None
) -> None:
    xray = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")],
        details=[
            _manual(
                "QA-7", "User logs in", "Given the login page", links=(_link(),), components=components
            )
        ],
    )

    result, patch = _single(xray, "t.robot", _tagged_robot(), component="Web")

    if expected is None:
        assert (result["status"], patch) == ("SKIPPED", None)
    else:
        assert result["changes"] == ["component"]
        assert patch == XrayTestPatch(key="QA-7", issue_id="id-QA-7", add_component="Web")


def test_component_is_not_compared_without_a_default_component() -> None:
    xray = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")],
        details=[_manual("QA-7", "User logs in", "Given the login page", links=(_link(),))],
    )

    result, _patch = _single(xray, "t.robot", _tagged_robot())

    assert result["status"] == "SKIPPED"


def test_test_of_another_type_is_an_error() -> None:
    details = _manual("QA-7", "User logs in", links=(_link(),))
    xray = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")], details=[replace(details, kind="other")]
    )

    result, patch = _single(xray, "t.robot", _tagged_robot())

    assert _error(result) == ("ERROR", "unsupported_test_type")
    assert patch is None


def _old_name(**values: object) -> XrayTestDetails:
    details = _manual("QA-7", "Old name", "Given another page", links=(_link(),))
    return replace(details, **values)


@pytest.mark.parametrize(
    ("details", "capabilities", "component", "reason"),
    [
        (_old_name(), XrayUpdateCapabilities(False, True), None, "jira_fields_unsupported"),
        (_old_name(editable=frozenset({"steps"})), None, None, "field_not_editable"),
        (_old_name(allowed_components=frozenset({"Api"})), None, "Web", "component_not_allowed"),
        (_old_name(links=()), XrayUpdateCapabilities(True, False), None, "link_type_unavailable"),
    ],
    ids=["cloud-jira-fields", "not-editable", "component", "link-type"],
)
def test_unsupported_changes_are_errors_and_nothing_of_that_scenario_is_written(
    details: XrayTestDetails,
    capabilities: XrayUpdateCapabilities | None,
    component: str | None,
    reason: str,
) -> None:
    xray = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")], details=[details], capabilities=capabilities
    )

    result, patch = _single(xray, "t.robot", _tagged_robot(), component=component)

    assert _error(result) == ("ERROR", reason)
    assert "steps" in result["changes"]
    assert patch is None


def test_cloud_still_updates_the_definition_when_no_jira_field_changed() -> None:
    details = _manual("QA-7", "User logs in", "Given another page", links=(_link(),))
    xray = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")],
        details=[details],
        capabilities=XrayUpdateCapabilities(jira_fields=False, story_link_type=True),
    )

    result, patch = _single(xray, "t.robot", _tagged_robot())

    assert (result["status"], result["changes"]) == ("UPDATED", ["steps"])
    assert patch is not None


def test_kind_change_on_a_test_with_preconditions_is_an_error() -> None:
    details = _cucumber("QA-7", "User logs in", "Given the login page", links=(_link(),))
    xray = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")], details=[replace(details, preconditions=1)]
    )

    result, patch = _single(xray, "t.robot", _tagged_robot())

    assert _error(result) == ("ERROR", "type_change_drops_preconditions")
    assert patch is None


@pytest.mark.parametrize(
    ("details", "unreadable", "reason"),
    [((), (), "details_missing"), ((), ("QA-7",), "details_unreadable")],
    ids=["missing", "unreadable"],
)
def test_test_details_that_cannot_be_read_are_errors(
    details: tuple[XrayTestDetails, ...], unreadable: tuple[str, ...], reason: str
) -> None:
    xray = _FakeXray(
        issues=[_test("QA-7"), _story("ABC-1")], details=details, unreadable=unreadable
    )

    result, patch = _single(xray, "t.robot", _tagged_robot())

    assert _error(result) == ("ERROR", reason)
    assert patch is None


def test_spec_problem_is_an_error() -> None:
    text = _lines(
        "*** Test Cases ***",
        "Scenario: User logs in",
        "    [Tags]    manual    XRay QA-7",
        "    Then nothing happened",
    )
    xray = _FakeXray(issues=[_test("QA-7")], details=[_manual("QA-7", "User logs in")])

    result, _patch = _single(xray, "t.robot", text)

    assert _error(result) == ("ERROR", "assertion_without_action")


THREE = _lines(
    "*** Test Cases ***",
    *[
        line
        for n in (1, 2, 3)
        for line in (f"Scenario: Test {n}", f"    [Tags]    manual    XRay QA-{n}", "    Given a")
    ],
)


def _three(outcomes: Sequence[object]) -> _FakeXray:
    return _FakeXray(
        issues=[_test(f"QA-{n}") for n in (1, 2, 3)],
        details=[_manual(f"QA-{n}", "Old", "Given a") for n in (1, 2, 3)],
        outcomes=outcomes,
    )


def _statuses(payload: dict) -> list[tuple[str, str | None]]:
    return [_error(result) for result in payload["results"]]


def test_rejected_update_is_an_error_and_the_run_continues() -> None:
    xray = _three([XrayUpdateRejectedError(), None, None])

    payload = _run(xray, ("t.robot", THREE))

    assert _statuses(payload) == [("ERROR", "rejected"), ("UPDATED", None), ("UPDATED", None)]
    assert (payload["stopped"], payload["stop_reason"]) == (False, None)
    assert payload["counts"] == {"UPDATED": 2, "WOULD_UPDATE": 0, "SKIPPED": 0, "ERROR": 1}


@pytest.mark.parametrize(
    "outcomes",
    [[ConnectorAuthError("denied")], [XrayUpdateRejectedError(), ConnectorAuthError("denied")]],
    ids=["first", "after-rejection"],
)
def test_auth_failure_before_any_write_raises(outcomes: list[object]) -> None:
    xray = _three(outcomes)

    with pytest.raises(ConnectorAuthError):
        _run(xray, ("t.robot", THREE))


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ConnectorAuthError("denied"), "auth_failed"),
        (XrayUpdateUncertainError(partial=False), "outcome_unknown"),
        (XrayUpdateUncertainError(partial=True), "partially_applied"),
        (XrayUpdateNotConfirmedError(), "not_confirmed"),
        (RuntimeError("boom"), "outcome_unknown"),
    ],
    ids=["auth", "uncertain", "partial", "not-confirmed", "unexpected"],
)
def test_failure_that_may_have_written_stops_the_run(error: Exception, reason: str) -> None:
    xray = _three([None, error])

    payload = _run(xray, ("t.robot", THREE))

    assert _statuses(payload) == [("UPDATED", None), ("ERROR", reason), ("ERROR", "not_attempted")]
    assert (payload["stopped"], payload["stop_reason"]) == (True, reason)
    assert len(xray.patches) == 2


def test_uncertain_first_write_stops_the_run() -> None:
    xray = _three([XrayUpdateUncertainError(partial=False)])

    payload = _run(xray, ("t.robot", THREE))

    assert _statuses(payload) == [
        ("ERROR", "outcome_unknown"),
        ("ERROR", "not_attempted"),
        ("ERROR", "not_attempted"),
    ]
    assert len(xray.patches) == 1


def test_lookup_failure_becomes_a_tool_failure() -> None:
    xray = _three([])
    xray.find_issues = _raise(ConnectorUnavailableError("down"))  # type: ignore[method-assign]

    with pytest.raises(ToolFailureError):
        _run(xray, ("t.robot", THREE))
    assert xray.patches == []


def _raise(error: Exception):  # noqa: ANN202
    def call(*_args: object) -> None:
        raise error

    return call


def test_approval_prompt_names_destination_and_scenarios_without_steps_or_jira_reads() -> None:
    xray = _three([])
    arguments = {"files": [{"path": "suite/t.robot", "content": THREE}]}

    hints = _tool(xray).approval_hints(arguments)
    dry = _tool(xray).approval_hints({**arguments, "dry_run": True})

    assert hints.title == "Update Xray tests from files"
    assert "Manual and Cucumber" in hints.summary
    assert hints.destination_label == "QA"
    assert hints.selected_title_count == 3
    assert hints.item_titles == ("t.robot:2 · Test 1", "t.robot:5 · Test 2", "t.robot:8 · Test 3")
    assert "Given a" not in repr(hints)
    assert dry.title.startswith("Dry run")
    assert (xray.lookups, xray.detail_calls, xray.patches) == ([], [], [])


def test_approval_prompt_lists_at_most_ten_scenarios() -> None:
    text = _lines(
        "*** Test Cases ***",
        *[line for n in range(12) for line in (f"Scenario: Test {n}", "    Given a")],
    )

    hints = _tool(_FakeXray()).approval_hints({"files": [{"path": "t.robot", "content": text}]})

    assert hints.selected_title_count == 12
    assert len(hints.item_titles) == 11
    assert hints.item_titles[-1] == "+2 more"
