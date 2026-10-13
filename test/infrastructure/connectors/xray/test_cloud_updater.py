"""XrayCloudImporter update behaviour (#398) through httpx.MockTransport; no live Xray."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence

import httpx
import pytest

from domain.errors import ConnectorAuthError, ConnectorError
from domain.test_management.xray import (
    CucumberDefinition,
    IssueLinkRef,
    ManualDefinition,
    XrayTestDetails,
    XrayTestPatch,
    XrayTestStep,
    XrayUpdateCapabilities,
    XrayUpdateNotConfirmedError,
    XrayUpdateRejectedError,
    XrayUpdateUncertainError,
)
from infrastructure.connectors.xray.cloud import XrayCloudImporter
from infrastructure.connectors.xray.schema import XraySchemaCache
from test.infrastructure.connectors.xray.test_cloud_importer import (
    BASE_URL,
    CLIENT_SECRET,
    TOKEN,
)

_TYPES = [
    {"id": "t-manual", "name": "Manual", "kind": "Steps"},
    {"id": "t-cucumber", "name": "Cucumber", "kind": "Gherkin"},
]
_DEFINITION = frozenset({"test_type", "steps", "gherkin", "scenario_type"})
_MUTATION = re.compile(r"mutation[^{]*\{\s*(\w+)")
_KEYS = re.compile(r"key in \(([^)]*)\)")

Reply = Callable[[dict[str, object]], httpx.Response]


def _test(
    key: str = "QA-7",
    *,
    issue_id: object = "10007",
    kind: str = "Steps",
    steps: Sequence[tuple[str, str, str]] = (),
    gherkin: object = None,
    scenario_type: object = None,
    links: Sequence[object] = (),
    components: Sequence[str] = (),
    preconditions: int = 0,
) -> dict[str, object]:
    return {
        "issueId": issue_id,
        "testType": {"id": "t", "name": kind, "kind": kind},
        "steps": [
            {"id": f"s{n}", "action": a, "data": d, "result": r}
            for n, (a, d, r) in enumerate(steps, 1)
        ],
        "gherkin": gherkin,
        "scenarioType": scenario_type,
        "preconditions": {"total": preconditions},
        "jira": {
            "key": key,
            "summary": "Login works",
            "components": [{"name": name} for name in components],
            "issuelinks": list(links),
        },
    }


def _ok(name: str, variables: dict[str, object]) -> httpx.Response:
    results: dict[str, object] = {
        "removeAllTestSteps": "ok",
        "addTestStep": {"id": "s9"},
        "updateTestType": {
            "issueId": variables.get("issueId"),
            "testType": variables.get("testType"),
        },
        "updateGherkinTestDefinition": {"issueId": variables.get("issueId")},
    }
    return httpx.Response(200, json={"data": {name: results[name]}})


class _Xray:
    def __init__(
        self,
        *tests: dict[str, object],
        types: list[dict[str, object]] = _TYPES,
        page_size: int = 100,
        after: dict[str, object] | None = None,
        replies: dict[int, Reply] | None = None,
        reads: list[Reply] | None = None,
    ) -> None:
        self.tests = list(tests)
        self.types = types
        self.page_size = page_size
        self.after = after
        self.replies = replies or {}
        self.read_replies = reads or []
        self.mutations: list[tuple[str, dict[str, object]]] = []
        self.searches: list[dict[str, object]] = []
        self.discoveries = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/authenticate":
            return httpx.Response(200, json=TOKEN)
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        body = json.loads(request.content)
        query, variables = body["query"], body["variables"]
        if "getProjectSettings" in query:
            self.discoveries += 1
            settings = {"testTypeSettings": {"testTypes": self.types}}
            return httpx.Response(200, json={"data": {"getProjectSettings": settings}})
        mutation = _MUTATION.search(query)
        if mutation:
            index = len(self.mutations)
            self.mutations.append((mutation.group(1), variables))
            reply = self.replies.get(index)
            response = reply(variables) if reply else _ok(mutation.group(1), variables)
            if response.status_code == 200 and self.after is not None:
                self.tests = [self.after]
            return response
        assert "getTests" in query
        self.searches.append(body)
        if self.read_replies:
            return self.read_replies.pop(0)(variables)
        keys = {k.strip() for k in _KEYS.search(variables["jql"]).group(1).split(",")}
        matching = [t for t in self.tests if t["jira"]["key"] in keys]  # type: ignore[index]
        start = variables["start"]
        page = matching[start : start + min(self.page_size, variables["limit"])]
        data = {"total": len(matching), "start": start, "limit": variables["limit"], "results": page}
        return httpx.Response(200, json={"data": {"getTests": data}})

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.mutations]


def _importer(xray: _Xray) -> XrayCloudImporter:
    return XrayCloudImporter(
        base_url=BASE_URL,
        client_id="cloud-client-id",
        client_secret=CLIENT_SECRET,
        project_key="QA",
        link_type="Test",
        cache=XraySchemaCache(),
        transport=httpx.MockTransport(xray),
    )


def _json(code: int, payload: object) -> Reply:
    def reply(variables: dict[str, object]) -> httpx.Response:
        return httpx.Response(code, json=payload)

    return reply


def _raise(error: Exception) -> Reply:
    def reply(variables: dict[str, object]) -> httpx.Response:
        raise error

    return reply


# --- details ---------------------------------------------------------------------


def test_manual_details_are_read_with_issue_id_links_and_definition_capabilities() -> None:
    xray = _Xray(
        _test(
            kind="steps",
            steps=[("Open login", "", "Form"), ("Submit", "user=ann", "")],
            links=[
                {"type": {"name": "Test"}, "outwardIssue": {"key": "ABC-1"}},
                {"type": {"name": "Blocks"}, "inwardIssue": {"key": "ABC-2"}},
            ],
            components=["UI"],
            preconditions=3,
        )
    )

    result = _importer(xray).test_details(["QA-7"])

    assert result.unreadable == frozenset()
    assert result.found == {
        "QA-7": XrayTestDetails(
            key="QA-7",
            issue_id="10007",
            summary="Login works",
            kind="manual",
            steps=(
                XrayTestStep(action="Open login", expected="Form"),
                XrayTestStep(action="Submit", data="user=ann"),
            ),
            components=("UI",),
            links=(
                IssueLinkRef("Test", "outward", "ABC-1"),
                IssueLinkRef("Blocks", "inward", "ABC-2"),
            ),
            preconditions=3,
            editable=_DEFINITION,
            allowed_components=None,
        )
    }
    [search] = xray.searches
    assert search["variables"]["jql"] == "key in (QA-7)"
    for selection in ("issueId", "testType", "steps", "scenarioType", "preconditions", "issuelinks"):
        assert selection in search["query"]


def test_cucumber_outline_kind_is_casefolded_and_keeps_its_scenario_type() -> None:
    xray = _Xray(_test(kind="GHERKIN", gherkin="Given a <x>", scenario_type="scenario_outline"))

    details = _importer(xray).test_details(["QA-7"]).found["QA-7"]

    assert (details.kind, details.scenario_type, details.gherkin) == (
        "cucumber",
        "scenario_outline",
        "Given a <x>",
    )


def test_other_kind_is_reported_as_other() -> None:
    xray = _Xray(_test(kind="Unstructured"))

    assert _importer(xray).test_details(["QA-7"]).found["QA-7"].kind == "other"


def test_missing_key_is_not_found_and_malformed_rows_are_unreadable() -> None:
    xray = _Xray(
        _test("QA-1", kind="Gherkin", gherkin="Given a", scenario_type="weird"),
        _test("QA-2", kind="Gherkin", gherkin="Given a", scenario_type=None),
        _test("QA-3", links=["nope"]),
        _test("QA-4"),
    )

    result = _importer(xray).test_details(["QA-1", "QA-2", "QA-3", "QA-4", "QA-9", "bad key"])

    assert result.unreadable == {"QA-1", "QA-2", "QA-3"}
    assert set(result.found) == {"QA-4"}


@pytest.mark.parametrize(
    "tests",
    [
        (_test("QA-7"), _test("QA-7")),
        (_test("QA-7", issue_id=""),),
        (_test("QA-7", issue_id=None),),
    ],
    ids=["duplicate-key", "empty-issue-id", "missing-issue-id"],
)
def test_incomplete_identity_fails_the_whole_read(tests: tuple[dict[str, object], ...]) -> None:
    with pytest.raises(ConnectorError):
        _importer(_Xray(*tests)).test_details(["QA-7"])


def test_details_are_paged_until_the_total_is_read() -> None:
    xray = _Xray(_test("QA-1"), _test("QA-2"), _test("QA-3"), page_size=2)

    result = _importer(xray).test_details(["QA-1", "QA-2", "QA-3"])

    assert set(result.found) == {"QA-1", "QA-2", "QA-3"}
    assert [s["variables"]["start"] for s in xray.searches] == [0, 2]


def test_details_are_read_in_chunks_of_fifty_keys() -> None:
    keys = [f"QA-{n}" for n in range(1, 121)]
    xray = _Xray(*(_test(key) for key in keys))

    result = _importer(xray).test_details(keys)

    assert len(result.found) == 120
    assert [len(_KEYS.search(s["variables"]["jql"]).group(1).split(",")) for s in xray.searches] == [
        50,
        50,
        20,
    ]


@pytest.mark.parametrize(
    "reply",
    [
        _json(200, {"errors": [{"message": "boom"}], "data": None}),
        _json(200, {"data": {"getTests": {"total": "1", "results": []}}}),
        _json(200, {"data": {"getTests": {"total": 2, "results": []}}}),
    ],
    ids=["graphql-errors", "bad-total", "short-page"],
)
def test_refused_or_incomplete_details_read_raises(reply: Reply) -> None:
    with pytest.raises(ConnectorError):
        _importer(_Xray(reads=[reply])).test_details(["QA-7"])


def test_type_switch_is_not_editable_without_both_project_types() -> None:
    xray = _Xray(_test(), types=[_TYPES[0]])

    details = _importer(xray).test_details(["QA-7"]).found["QA-7"]

    assert details.editable == _DEFINITION - {"test_type"}


def test_capabilities_exclude_jira_fields_without_any_request() -> None:
    xray = _Xray()

    assert _importer(xray).capabilities() == XrayUpdateCapabilities(
        jira_fields=False, story_link_type=True
    )
    assert (xray.searches, xray.discoveries) == ([], 0)


def test_lowercase_project_type_kinds_still_support_creating_tests() -> None:
    types = [
        {"id": "t-manual", "name": "Manual", "kind": "steps"},
        {"id": "t-cucumber", "name": "Cucumber", "kind": "GHERKIN"},
    ]

    schema = _importer(_Xray(types=types)).schema()

    assert (schema.supports_manual, schema.supports_cucumber) == (True, True)


# --- update_test -------------------------------------------------------------------

_STEPS = (XrayTestStep(action="Open login", expected="Form"), XrayTestStep(action="Submit"))
_STEP_VARS = [
    {"action": "Open login", "data": "", "result": "Form"},
    {"action": "Submit", "data": "", "result": ""},
]
_CUCUMBER = _test(kind="Gherkin", gherkin="Given a", scenario_type="scenario")


def _patch(**members: object) -> XrayTestPatch:
    return XrayTestPatch(key="QA-7", issue_id="10007", **members)  # type: ignore[arg-type]


def test_steps_only_update_replaces_the_steps_without_changing_the_type() -> None:
    xray = _Xray(_test(steps=[("Old", "", "")]))

    _importer(xray).update_test(_patch(definition=ManualDefinition(_STEPS)))

    assert xray.mutations == [
        ("removeAllTestSteps", {"issueId": "10007"}),
        ("addTestStep", {"issueId": "10007", "step": _STEP_VARS[0]}),
        ("addTestStep", {"issueId": "10007", "step": _STEP_VARS[1]}),
    ]
    assert xray.searches == []


def test_gherkin_only_update_sends_one_mutation_and_no_type_change() -> None:
    xray = _Xray(_CUCUMBER)

    _importer(xray).update_test(_patch(definition=CucumberDefinition("Given b")))

    assert xray.mutations == [
        ("updateGherkinTestDefinition", {"issueId": "10007", "gherkin": "Given b"})
    ]
    assert xray.searches == []


def test_outline_only_update_writes_gherkin_and_reads_back_the_scenario_type() -> None:
    gherkin = "Given a <x>\n\nExamples:\n  | x |\n  | 1 |"
    after = _test(kind="Gherkin", gherkin=gherkin, scenario_type="scenario_outline")
    xray = _Xray(_CUCUMBER, after=after)

    _importer(xray).update_test(
        _patch(
            scenario_type_change=("scenario", "scenario_outline"),
            definition=CucumberDefinition(gherkin, outline=True),
        )
    )

    assert xray.names == ["updateGherkinTestDefinition"]
    assert len(xray.searches) == 1


def test_outline_update_not_shown_by_the_read_back_is_not_confirmed() -> None:
    xray = _Xray(_CUCUMBER, after=_test(kind="Gherkin", gherkin="Given a <x>", scenario_type="scenario"))

    with pytest.raises(XrayUpdateNotConfirmedError):
        _importer(xray).update_test(
            _patch(
                scenario_type_change=("scenario", "scenario_outline"),
                definition=CucumberDefinition("Given a <x>", outline=True),
            )
        )


def test_manual_to_cucumber_clears_steps_then_changes_type_then_writes_gherkin() -> None:
    after = _test(kind="Gherkin", gherkin="Given b", scenario_type="scenario")
    xray = _Xray(_test(steps=[("Old", "", "")]), after=after)

    _importer(xray).update_test(
        _patch(kind_change=("manual", "cucumber"), definition=CucumberDefinition("Given b"))
    )

    assert xray.mutations == [
        ("removeAllTestSteps", {"issueId": "10007"}),
        ("updateTestType", {"issueId": "10007", "testType": {"id": "t-cucumber"}}),
        ("updateGherkinTestDefinition", {"issueId": "10007", "gherkin": "Given b"}),
    ]
    assert len(xray.searches) == 1


def test_cucumber_to_manual_clears_gherkin_then_changes_type_then_adds_steps() -> None:
    after = _test(steps=[("Open login", "", "Form"), ("Submit", "", "")], gherkin="")
    xray = _Xray(_CUCUMBER, after=after)

    _importer(xray).update_test(
        _patch(kind_change=("cucumber", "manual"), definition=ManualDefinition(_STEPS))
    )

    assert xray.mutations == [
        ("updateGherkinTestDefinition", {"issueId": "10007", "gherkin": ""}),
        ("updateTestType", {"issueId": "10007", "testType": {"id": "t-manual"}}),
        ("addTestStep", {"issueId": "10007", "step": _STEP_VARS[0]}),
        ("addTestStep", {"issueId": "10007", "step": _STEP_VARS[1]}),
    ]


@pytest.mark.parametrize(
    "after",
    [
        _test(kind="Gherkin", gherkin="Given b", scenario_type="scenario", steps=[("Old", "", "")]),
        _test(steps=[("Old", "", "")]),
    ],
    ids=["old-steps-kept", "kind-unchanged"],
)
def test_kind_switch_that_does_not_read_back_is_not_confirmed(after: dict[str, object]) -> None:
    xray = _Xray(_test(steps=[("Old", "", "")]), after=after)

    with pytest.raises(XrayUpdateNotConfirmedError):
        _importer(xray).update_test(
            _patch(kind_change=("manual", "cucumber"), definition=CucumberDefinition("Given b"))
        )


@pytest.mark.parametrize(
    "patch",
    [
        _patch(summary="New"),
        _patch(add_component="UI"),
        _patch(add_story_link=IssueLinkRef("Test", "outward", "ABC-1")),
        _patch(summary="New", definition=CucumberDefinition("Given b")),
    ],
    ids=["summary", "component", "story-link", "mixed"],
)
def test_patch_with_jira_fields_is_refused_before_any_mutation(patch: XrayTestPatch) -> None:
    xray = _Xray(_CUCUMBER)

    with pytest.raises(XrayUpdateRejectedError):
        _importer(xray).update_test(patch)
    assert xray.mutations == []


def test_kind_switch_without_the_target_project_type_is_refused() -> None:
    xray = _Xray(_test(), types=[_TYPES[0]])

    with pytest.raises(XrayUpdateRejectedError):
        _importer(xray).update_test(
            _patch(kind_change=("manual", "cucumber"), definition=CucumberDefinition("Given b"))
        )
    assert xray.mutations == []


@pytest.mark.parametrize(
    "reply",
    [
        _json(200, {"errors": [{"message": f"bad {TOKEN}"}], "data": None}),
        _json(200, {"errors": [{"message": "bad"}], "data": {"updateGherkinTestDefinition": None}}),
        _json(400, {"error": CLIENT_SECRET}),
        _json(403, {}),
        _json(404, {}),
    ],
    ids=["graphql-errors", "graphql-errors-null-result", "400", "403", "404"],
)
def test_first_mutation_refused_is_rejected(reply: Reply) -> None:
    xray = _Xray(_CUCUMBER, replies={0: reply})

    with pytest.raises(XrayUpdateRejectedError) as caught:
        _importer(xray).update_test(_patch(definition=CucumberDefinition("Given b")))
    assert TOKEN not in str(caught.value) and CLIENT_SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "reply",
    [
        _json(200, {"data": {"updateGherkinTestDefinition": None}}),
        _json(200, {"data": {"updateGherkinTestDefinition": {"issueId": "99"}}}),
        _json(200, {"data": None}),
        _json(500, {}),
        _raise(httpx.ReadTimeout("slow")),
    ],
    ids=["null-result", "other-issue-id", "no-data", "500", "timeout"],
)
def test_first_mutation_with_unknown_outcome_is_uncertain(reply: Reply) -> None:
    xray = _Xray(_CUCUMBER, replies={0: reply})

    with pytest.raises(XrayUpdateUncertainError) as caught:
        _importer(xray).update_test(_patch(definition=CucumberDefinition("Given b")))
    assert caught.value.partial is False


def test_first_mutation_unauthorized_raises_auth_error() -> None:
    xray = _Xray(_CUCUMBER, replies={0: _json(401, {})})

    with pytest.raises(ConnectorAuthError):
        _importer(xray).update_test(_patch(definition=CucumberDefinition("Given b")))


@pytest.mark.parametrize(
    "replies",
    [
        {1: _json(200, {"errors": [{"message": "bad"}], "data": None})},
        {1: _json(400, {})},
        {1: _json(401, {}), 2: _json(401, {})},
        {1: _json(500, {})},
        {1: _json(200, {"data": {"addTestStep": None}})},
    ],
    ids=["graphql-errors", "400", "401-after-retry", "500", "null-result"],
)
def test_failure_after_a_successful_mutation_is_partial(replies: dict[int, Reply]) -> None:
    xray = _Xray(_test(steps=[("Old", "", "")]), replies=replies)

    with pytest.raises(XrayUpdateUncertainError) as caught:
        _importer(xray).update_test(_patch(definition=ManualDefinition(_STEPS)))
    assert caught.value.partial is True


def test_type_change_answered_with_another_type_is_partial() -> None:
    def other_type(variables: dict[str, object]) -> httpx.Response:
        result = {"issueId": "10007", "testType": {"id": "t-manual"}}
        return httpx.Response(200, json={"data": {"updateTestType": result}})

    xray = _Xray(_test(steps=[("Old", "", "")]), replies={1: other_type})

    with pytest.raises(XrayUpdateUncertainError) as caught:
        _importer(xray).update_test(
            _patch(kind_change=("manual", "cucumber"), definition=CucumberDefinition("Given b"))
        )
    assert caught.value.partial is True
