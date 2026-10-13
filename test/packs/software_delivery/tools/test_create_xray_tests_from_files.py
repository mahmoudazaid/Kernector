"""Seam: ``CreateXrayTestsFromFilesTool.run`` with a fake Xray importer and lookup (#397)."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorUnavailableError,
    ToolFailureError,
)
from domain.test_management.xray import (
    IssueLookupResult,
    JiraIssueSummary,
    XrayCreateWarning,
    XrayImportResult,
    XrayRequiredFieldsError,
    XrayTestCreateSchema,
    XrayTestSpec,
    XrayTestStep,
)
from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError, XrayExportValidationError
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.tools.create_xray_tests_from_files import (
    TOOL_NAME,
    CreateXrayTestsFromFilesTool,
)

TAGS = TestFileTagConfig(test_marker="XRay", story_marker="Story", manual_tags=("manual",))
STORY_TYPES = frozenset({"Story"})


def _story(key: str) -> JiraIssueSummary:
    return JiraIssueSummary(key, f"Story {key}", "10001", "Story", False)


def _test(key: str, summary: str = "Some test") -> JiraIssueSummary:
    return JiraIssueSummary(key, summary, "10002", "Test", True)


class _FakeXray:
    """Fake importer + lookup; creates sequential keys unless told otherwise."""

    def __init__(
        self,
        *,
        issues: Sequence[JiraIssueSummary] = (),
        missing: Sequence[str] = (),
        linked: dict[str, tuple[JiraIssueSummary, ...]] | None = None,
        schema: XrayTestCreateSchema | None = None,
        outcomes: Sequence[object] = (),
    ) -> None:
        self.issues = {issue.key: issue for issue in issues}
        self.missing = frozenset(missing)
        self.linked = linked or {}
        self.schema_value = schema or XrayTestCreateSchema(
            project_key="QA",
            supports_manual=True,
            supports_cucumber=True,
            supports_issue_link=True,
            supports_cucumber_outline=True,
        )
        self.outcomes = list(outcomes)
        self.created: list[XrayTestSpec] = []
        self.lookups: list[tuple[str, ...]] = []
        self.linked_calls: list[str] = []
        self.lookup_error: Exception | None = None
        self._next = 100

    def schema(self) -> XrayTestCreateSchema:
        return self.schema_value

    def find_issues(self, keys: Sequence[str]) -> IssueLookupResult:
        self.lookups.append(tuple(keys))
        if self.lookup_error is not None:
            raise self.lookup_error
        return IssueLookupResult(
            found={k: self.issues[k] for k in keys if k in self.issues},
            missing=frozenset(k for k in keys if k in self.missing),
        )

    def linked_tests(self, story_key: str) -> tuple[JiraIssueSummary, ...]:
        self.linked_calls.append(story_key)
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.linked.get(story_key, ())

    def import_tests(self, specs: Sequence[XrayTestSpec]) -> XrayImportResult:
        assert len(specs) == 1
        self.created.append(specs[0])
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, XrayImportResult):
            return outcome
        self._next += 1
        return XrayImportResult(created_keys=(f"QA-{self._next}",), failed_count=0)


def _tool(xray: _FakeXray, *, component: str | None = None) -> CreateXrayTestsFromFilesTool:
    return CreateXrayTestsFromFilesTool(
        importer=xray,
        lookup=xray,
        tags=TAGS,
        story_issue_types=STORY_TYPES,
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


def _robot(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_untagged_manual_robot_scenario_is_created_and_linked_to_its_story() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")])
    text = _robot(
        "*** Test Cases ***",
        "Scenario: User logs in",
        "    [Tags]    manual    Story ABC-1",
        "    Given the login page",
        "    When the user submits    admin",
    )

    payload = _run(xray, ("tests/login.robot", text))

    assert _tool(xray).name == TOOL_NAME == "software_delivery.create_xray_tests_from_files"
    [spec] = xray.created
    assert spec.title == "User logs in"
    assert spec.kind == "manual"
    assert spec.link_issue_key == spec.source_issue_key == "ABC-1"
    assert spec.steps == (
        XrayTestStep(action="Given the login page"),
        XrayTestStep(action="When the user submits    admin"),
    )
    [result] = payload["results"]
    assert result == {
        "path": "tests/login.robot",
        "line": 2,
        "summary": "User logs in",
        "status": "CREATED",
        "key": "QA-101",
        "candidate_keys": [],
        "story_key": "ABC-1",
        "reason": None,
    }
    assert payload["created"] == {"tests/login.robot::User logs in": "QA-101"}
    assert payload["dry_run"] is False
    assert payload["stopped"] is False
    assert payload["counts"]["CREATED"] == 1


def _feature(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_tagged_scenarios_are_ignored() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")])
    text = _robot(
        "*** Test Cases ***",
        "Scenario: Already in Xray",
        "    [Tags]    XRay QA-7    Story ABC-1",
        "    Given something",
    )

    payload = _run(xray, ("t.robot", text))

    assert payload["results"] == []
    assert xray.created == []
    assert xray.lookups == []


def test_then_and_but_lines_become_the_expected_result_of_the_previous_action() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")])
    text = _robot(
        "*** Test Cases ***",
        "Scenario: Login",
        "    [Tags]    manual    Story ABC-1",
        "    Given the login page",
        "    And a user    admin",
        "    When the user submits",
        "    Then the dashboard is shown",
        "    And a welcome banner",
        "    But no error",
        "    When the user logs out",
        "    Then the login page is shown",
    )

    _run(xray, ("t.robot", text))

    assert xray.created[0].steps == (
        XrayTestStep(action="Given the login page\nAnd a user    admin"),
        XrayTestStep(
            action="When the user submits",
            expected="Then the dashboard is shown\nAnd a welcome banner\nBut no error",
        ),
        XrayTestStep(action="When the user logs out", expected="Then the login page is shown"),
    )


def test_assertion_without_a_previous_action_is_an_error_and_not_created() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")])
    text = _robot(
        "*** Test Cases ***",
        "Scenario: Assert first",
        "    [Tags]    manual    Story ABC-1",
        "    Then the dashboard is shown",
        "    When the user clicks",
    )

    [result] = _run(xray, ("t.robot", text))["results"]

    assert (result["status"], result["reason"]) == ("ERROR", "assertion_without_action")
    assert xray.created == []


def test_manual_data_tables_and_doc_strings_stay_with_their_line() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")])
    text = _feature(
        "Feature: Login",
        "  Background:",
        "    Given a clean database",
        "  @manual @Story:ABC-1",
        "  Scenario: Users",
        "    Given these users",
        "      | name | role |",
        "      | ann  | admin |",
        "    Then the response is",
        '      """json',
        '      {"ok": true}',
        '      """',
    )

    _run(xray, ("f.feature", text))

    assert xray.created[0].steps == (
        XrayTestStep(action="Given a clean database"),
        XrayTestStep(
            action="Given these users\n| name | role |\n| ann | admin |",
            expected='Then the response is\n"""json\n      {"ok": true}\n"""',
        ),
    )


def test_cucumber_scenario_gherkin_keeps_background_tables_and_doc_strings() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")])
    text = _feature(
        "@Story:ABC-1",
        "Feature: Login",
        "  Background:",
        "    Given a clean database",
        "  Scenario: Users",
        "    Given these users",
        "      | name |",
        "      | ann  |",
        "    When the API is called with",
        '      """',
        "      body",
        '      """',
        "    Then it works",
    )

    _run(xray, ("f.feature", text))

    [spec] = xray.created
    assert spec.kind == "cucumber"
    assert spec.outline is False
    assert spec.gherkin == "\n".join(
        [
            "Given a clean database",
            "Given these users",
            "  | name |",
            "  | ann |",
            "When the API is called with",
            '  """',
            "      body",
            '  """',
            "Then it works",
        ]
    )


def test_scenario_outline_keeps_its_examples_and_is_an_outline_spec() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")])
    text = _feature(
        "@Story:ABC-1",
        "Feature: Login",
        "  Scenario Outline: Login as <role>",
        "    Given a <role>",
        "    @fast",
        "    Examples: Roles",
        "      | role |",
        "      | admin |",
    )

    _run(xray, ("f.feature", text))

    [spec] = xray.created
    assert spec.outline is True
    assert spec.gherkin == "\n".join(
        ["Given a <role>", "", "@fast", "Examples: Roles", "  | role |", "  | admin |"]
    )


def test_outline_without_outline_support_is_an_error_and_not_created() -> None:
    xray = _FakeXray(
        issues=[_story("ABC-1")],
        schema=XrayTestCreateSchema(
            project_key="QA",
            supports_manual=True,
            supports_cucumber=True,
            supports_issue_link=True,
            supports_cucumber_outline=False,
        ),
    )
    text = _feature(
        "@Story:ABC-1",
        "Feature: Login",
        "  Scenario Outline: Login as <role>",
        "    Given a <role>",
        "    Examples:",
        "      | role |",
        "      | admin |",
    )

    [result] = _run(xray, ("f.feature", text))["results"]

    assert (result["status"], result["reason"]) == ("ERROR", "outline_unsupported")
    assert xray.created == []


def test_manual_outline_is_an_error_and_its_examples_are_never_dropped() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")])
    text = _feature(
        "@Story:ABC-1",
        "Feature: Login",
        "  @manual",
        "  Scenario Outline: Login as <role>",
        "    Given a <role>",
        "    Examples:",
        "      | role |",
        "      | admin |",
    )

    [result] = _run(xray, ("f.feature", text))["results"]

    assert (result["status"], result["reason"]) == ("ERROR", "manual_outline_unsupported")
    assert xray.created == []


def test_configured_default_component_is_set_on_every_spec() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")])
    text = _robot(
        "*** Settings ***",
        "Default Tags    Story ABC-1",
        "*** Test Cases ***",
        "Scenario: One",
        "    Given a",
        "Scenario: Two",
        "    Given b",
    )

    _run(xray, ("t.robot", text), component="Checkout")

    assert [spec.component for spec in xray.created] == ["Checkout", "Checkout"]


def _bug(key: str) -> JiraIssueSummary:
    return JiraIssueSummary(key, "A bug", "10003", "Bug", False)


def _one(xray: _FakeXray, text: str, path: str = "t.robot") -> dict:
    [result] = [r for r in _run(xray, (path, text))["results"] if r["summary"] == "Login"]
    return result


LOGIN_WITH = "Scenario: Login"


def _login(tags: str, *, settings: str = "") -> str:
    lines = ["*** Settings ***", settings] if settings else []
    return _robot(*lines, "*** Test Cases ***", LOGIN_WITH, f"    [Tags]    {tags}", "    Given a")


def test_bare_key_that_is_a_test_exists_untagged_and_nothing_is_created() -> None:
    xray = _FakeXray(issues=[_story("ABC-1"), _test("QA-5")])

    result = _one(xray, _login("QA-5    Story ABC-1"))

    assert (result["status"], result["key"]) == ("EXISTS_UNTAGGED", "QA-5")
    assert xray.created == []


def test_claimed_bare_test_key_is_an_error_and_never_the_story() -> None:
    xray = _FakeXray(issues=[_story("ABC-1"), _test("QA-5")])
    text = _robot(
        "*** Settings ***",
        "Default Tags    Story ABC-1",
        "*** Test Cases ***",
        "Scenario: Tagged",
        "    [Tags]    XRay QA-5",
        "    Given a",
        LOGIN_WITH,
        "    [Tags]    QA-5",
        "    Given a",
    )

    result = _one(xray, text)

    assert (result["status"], result["reason"], result["key"]) == (
        "ERROR",
        "test_key_claimed",
        "QA-5",
    )
    assert xray.created == []


def test_missing_or_unresolved_bare_key_is_an_error_not_a_fallback_story() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")], missing=["ABC-9"])
    settings = "Default Tags    Story ABC-1"

    missing = _one(xray, _login("ABC-9", settings=settings))
    unresolved = _one(xray, _login("ABC-8", settings=settings))

    assert (missing["status"], missing["reason"]) == ("ERROR", "issue_not_found")
    assert (unresolved["status"], unresolved["reason"]) == ("ERROR", "issue_unresolved")
    assert xray.created == []


def test_two_bare_test_keys_are_ambiguous() -> None:
    xray = _FakeXray(issues=[_story("ABC-1"), _test("QA-5"), _test("QA-6")])

    result = _one(xray, _login("QA-5    QA-6    Story ABC-1"))

    assert (result["status"], result["reason"]) == ("AMBIGUOUS", "multiple_tests")
    assert result["candidate_keys"] == ["QA-5", "QA-6"]
    assert xray.created == []


def test_linked_test_with_the_exact_summary_exists_untagged() -> None:
    xray = _FakeXray(
        issues=[_story("ABC-1")],
        linked={"ABC-1": (_test("QA-5", "Login"), _test("QA-6", "Logout"))},
    )

    result = _one(xray, _login("Story ABC-1"))

    assert (result["status"], result["key"]) == ("EXISTS_UNTAGGED", "QA-5")
    assert xray.created == []


def test_summary_match_is_exact_and_whitespace_differences_do_not_match() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")], linked={"ABC-1": (_test("QA-5", "Login "),)})

    result = _one(xray, _login("Story ABC-1"))

    assert result["status"] == "CREATED"


def test_linked_test_claimed_by_a_tagged_scenario_is_skipped() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")], linked={"ABC-1": (_test("QA-5", "Login"),)})
    tagged = _robot(
        "*** Test Cases ***",
        LOGIN_WITH,
        "    [Tags]    XRay QA-5    Story ABC-1",
        "    Given a",
    )

    payload = _run(xray, ("tagged.robot", tagged), ("t.robot", _login("Story ABC-1")))

    [result] = payload["results"]
    assert result["status"] == "CREATED"


def test_two_linked_tests_with_the_same_summary_are_ambiguous() -> None:
    xray = _FakeXray(
        issues=[_story("ABC-1")],
        linked={"ABC-1": (_test("QA-5", "Login"), _test("QA-9", "Login"))},
    )

    result = _one(xray, _login("Story ABC-1"))

    assert (result["status"], result["reason"]) == ("AMBIGUOUS", "multiple_tests")
    assert result["candidate_keys"] == ["QA-5", "QA-9"]


def test_repeated_story_summary_in_the_run_is_created_once() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")])
    text = _login("Story ABC-1")

    payload = _run(xray, ("a.robot", text), ("b.robot", text))

    first, second = payload["results"]
    assert (first["status"], first["key"]) == ("CREATED", "QA-101")
    assert (second["status"], second["reason"]) == ("AMBIGUOUS", "repeated_in_run")
    assert second["candidate_keys"] == ["QA-101"]
    assert len(xray.created) == 1
    assert payload["created"] == {"a.robot::Login": "QA-101"}


def test_repeated_story_summary_is_ambiguous_in_dry_run_too() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")])
    text = _login("Story ABC-1")

    first, second = _run(xray, ("a.robot", text), ("b.robot", text), dry_run=True)["results"]

    assert first["status"] == "WOULD_CREATE"
    assert (second["status"], second["reason"], second["candidate_keys"]) == (
        "AMBIGUOUS",
        "repeated_in_run",
        [],
    )


def test_repeat_of_an_existing_match_is_ambiguous_with_that_key() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")], linked={"ABC-1": (_test("QA-5", "Login"),)})
    text = _login("Story ABC-1")

    first, second = _run(xray, ("a.robot", text), ("b.robot", text))["results"]

    assert (first["status"], first["key"]) == ("EXISTS_UNTAGGED", "QA-5")
    assert (second["status"], second["reason"], second["candidate_keys"]) == (
        "AMBIGUOUS",
        "repeated_in_run",
        ["QA-5"],
    )
    assert xray.created == []


def test_duplicate_scenario_identity_or_path_is_rejected_before_any_jira_call() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")])
    twice = _robot(
        "*** Test Cases ***",
        LOGIN_WITH,
        "    [Tags]    Story ABC-1",
        "    Given a",
        LOGIN_WITH,
        "    [Tags]    Story ABC-1",
        "    Given b",
    )

    with pytest.raises(TestFileValidationError) as summary_error:
        _run(xray, ("t.robot", twice))
    with pytest.raises(TestFileValidationError) as path_error:
        _run(xray, ("t.robot", _login("Story ABC-1")), (" t.robot", _login("Story ABC-1")))

    assert (summary_error.value.reason, summary_error.value.line) == (
        Reason.DUPLICATE_SCENARIO_SUMMARY,
        5,
    )
    assert path_error.value.reason == Reason.DUPLICATE_FILE_PATH
    assert xray.lookups == [] and xray.created == []


def test_robot_story_order_is_story_tag_then_bare_key_then_default_tags() -> None:
    xray = _FakeXray(issues=[_story("ABC-1"), _story("ABC-2"), _story("ABC-3")])
    settings = "Default Tags    Story ABC-1"

    tagged = _one(xray, _login("ABC-2    Story ABC-3", settings=settings))
    bare = _one(xray, _login("ABC-2", settings=settings))
    default = _one(xray, _login("smoke", settings=settings))

    assert [tagged["story_key"], bare["story_key"], default["story_key"]] == [
        "ABC-3",
        "ABC-2",
        "ABC-1",
    ]


def test_story_problems_are_reported_and_nothing_is_created() -> None:
    xray = _FakeXray(issues=[_bug("ABC-4")], missing=["ABC-9"])

    none = _one(xray, _login("smoke"))
    missing = _one(xray, _login("Story ABC-9"))
    bug = _one(xray, _login("Story ABC-4"))
    unresolved = _one(xray, _login("Story ABC-7"))

    assert [(r["status"], r["reason"]) for r in (none, missing, bug, unresolved)] == [
        ("NO_STORY", "no_story"),
        ("NO_STORY", "story_not_found"),
        ("NO_STORY", "not_a_story"),
        ("ERROR", "story_unresolved"),
    ]
    assert xray.created == []


def test_story_type_may_be_configured_by_issue_type_id() -> None:
    xray = _FakeXray(issues=[JiraIssueSummary("ABC-1", "S", "777", "Epic-ish", False)])

    result = json.loads(
        CreateXrayTestsFromFilesTool(
            importer=xray,
            lookup=xray,
            tags=TAGS,
            story_issue_types=frozenset({"777"}),
        ).run({"files": [{"path": "t.robot", "content": _login("Story ABC-1")}]})
    )["results"][0]

    assert result["status"] == "CREATED"


def _three() -> str:
    return _robot(
        "*** Settings ***",
        "Default Tags    Story ABC-1",
        "*** Test Cases ***",
        "Scenario: One",
        "    Given a",
        "Scenario: Two",
        "    Given b",
        "Scenario: Three",
        "    Given c",
    )


def _statuses(payload: dict) -> list[tuple[str, str | None, str | None]]:
    return [(r["status"], r["reason"], r["key"]) for r in payload["results"]]


def test_without_link_support_nothing_is_created() -> None:
    xray = _FakeXray(
        issues=[_story("ABC-1")],
        schema=XrayTestCreateSchema(
            project_key="QA",
            supports_manual=True,
            supports_cucumber=True,
            supports_issue_link=False,
            supports_cucumber_outline=True,
        ),
    )

    payload = _run(xray, ("t.robot", _three()))

    assert {(r["status"], r["reason"]) for r in payload["results"]} == {
        ("ERROR", "link_unsupported")
    }
    assert xray.created == []


def test_dry_run_reports_the_plan_and_never_creates() -> None:
    xray = _FakeXray(
        issues=[_story("ABC-1"), _test("QA-5")],
        linked={"ABC-1": (_test("QA-7", "Two"), _test("QA-8", "Two"))},
    )
    text = _robot(
        "*** Settings ***",
        "Default Tags    Story ABC-1",
        "*** Test Cases ***",
        "Scenario: One",
        "    Given a",
        "Scenario: Two",
        "    Given b",
        "Scenario: Three",
        "    [Tags]    QA-5",
        "    Given c",
    )

    payload = _run(xray, ("t.robot", text), dry_run=True)

    assert _statuses(payload) == [
        ("WOULD_CREATE", None, None),
        ("AMBIGUOUS", "multiple_tests", None),
        ("EXISTS_UNTAGGED", None, "QA-5"),
    ]
    assert payload["dry_run"] is True
    assert payload["created"] == {}
    assert xray.created == []


def test_lookup_failures_fail_closed_before_any_create() -> None:
    for error, expected in (
        (ConnectorUnavailableError("x"), ToolFailureError),
        (ConnectorError("x"), ToolFailureError),
        (ConnectorAuthError("x"), ConnectorAuthError),
    ):
        xray = _FakeXray(issues=[_story("ABC-1")])
        xray.lookup_error = error

        with pytest.raises(expected):
            _run(xray, ("t.robot", _three()))

        assert xray.created == []


def test_rejection_and_required_fields_are_errors_and_the_run_continues() -> None:
    xray = _FakeXray(
        issues=[_story("ABC-1")],
        outcomes=[
            XrayImportResult(created_keys=(), failed_count=1),
            XrayRequiredFieldsError(("Team",)),
        ],
    )

    payload = _run(xray, ("t.robot", _three()))

    assert _statuses(payload) == [
        ("ERROR", "rejected", None),
        ("ERROR", "required_fields", None),
        ("CREATED", None, "QA-101"),
    ]
    assert payload["stopped"] is False


def test_indeterminate_first_create_stops_without_retry() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")], outcomes=[ConnectorUnavailableError("x")])

    payload = _run(xray, ("t.robot", _three()))

    assert _statuses(payload) == [
        ("ERROR", "outcome_unknown", None),
        ("ERROR", "not_attempted", None),
        ("ERROR", "not_attempted", None),
    ]
    assert (payload["stopped"], payload["stop_reason"]) == (True, "outcome_unknown")
    assert len(xray.created) == 1


def test_indeterminate_failure_after_a_create_keeps_the_created_key() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")], outcomes=[None, ConnectorError("x")])

    payload = _run(xray, ("t.robot", _three()))

    assert _statuses(payload) == [
        ("CREATED", None, "QA-101"),
        ("ERROR", "outcome_unknown", None),
        ("ERROR", "not_attempted", None),
    ]
    assert payload["created"] == {"t.robot::One": "QA-101"}


def test_auth_failure_on_the_first_create_raises() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")], outcomes=[ConnectorAuthError("x")])

    with pytest.raises(ConnectorAuthError):
        _run(xray, ("t.robot", _three()))


def test_auth_failure_after_a_create_returns_results_with_the_known_key() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")], outcomes=[None, ConnectorAuthError("x")])

    payload = _run(xray, ("t.robot", _three()))

    assert _statuses(payload) == [
        ("CREATED", None, "QA-101"),
        ("ERROR", "auth_failed", None),
        ("ERROR", "not_attempted", None),
    ]
    assert (payload["stopped"], payload["stop_reason"]) == (True, "auth_failed")


def test_unconfirmed_link_is_an_error_with_its_key_and_stops_the_run() -> None:
    xray = _FakeXray(
        issues=[_story("ABC-1")],
        outcomes=[
            XrayImportResult(
                created_keys=("QA-50",),
                failed_count=0,
                warnings=(XrayCreateWarning("QA-50", "link_not_confirmed"),),
            )
        ],
    )

    payload = _run(xray, ("t.robot", _three()))

    assert _statuses(payload) == [
        ("ERROR", "link_not_confirmed", "QA-50"),
        ("ERROR", "not_attempted", None),
        ("ERROR", "not_attempted", None),
    ]
    assert payload["created"] == {"t.robot::One": "QA-50"}
    assert payload["counts"]["ERROR"] == 3


def test_approval_hints_give_project_and_untagged_count_only() -> None:
    xray = _FakeXray(issues=[_story("ABC-1")])

    hints = _tool(xray).approval_hints(
        {"files": [{"path": "t.robot", "content": _three()}], "dry_run": True}
    )

    assert hints.destination_label == "QA"
    assert hints.selected_title_count == 3
    assert "Given" not in hints.summary
    assert xray.lookups == [] and xray.created == []


def test_arguments_are_validated() -> None:
    xray = _FakeXray()
    tool = _tool(xray)

    for arguments in (
        {},
        {"files": [{"path": "t.robot", "content": _three()}], "extra": 1},
        {"files": [{"path": "t.robot", "content": _three()}], "dry_run": "yes"},
        {"files": "nope"},
    ):
        with pytest.raises(XrayExportValidationError):
            tool.run(arguments)
