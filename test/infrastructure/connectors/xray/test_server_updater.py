"""XrayServerImporter update behaviour (#398) through httpx.MockTransport; no live Jira."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

import httpx
import pytest

from domain.errors import ConnectorAuthError, ConnectorUnavailableError
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
from infrastructure.connectors.xray.schema import XraySchemaCache
from infrastructure.connectors.xray.server import XrayServerImporter
from test.infrastructure.connectors.xray.test_server_schema import (
    API,
    BASE_URL,
    CUCUMBER_TYPE,
    MANUAL_STEPS,
    SCENARIO,
    TEST_TYPE,
    TOKEN,
)

PRECONDITIONS = "com.xpandit.plugins.xray:test-precondition-custom-field"
ALL_EDITABLE = frozenset(
    {"summary", "test_type", "steps", "gherkin", "scenario_type", "component", "story_link"}
)

Reply = Callable[[httpx.Request], httpx.Response]


def _editmeta(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "summary": {"operations": ["set"]},
        "components": {
            "operations": ["add", "set", "remove"],
            "allowedValues": [{"id": "1", "name": "UI"}, {"id": "2", "name": "API"}],
        },
        "issuelinks": {"operations": ["add"]},
        "customfield_10200": {
            "operations": ["set"],
            "schema": {"custom": TEST_TYPE},
            "allowedValues": [
                {"id": "301", "value": "Manual"},
                {"id": "302", "value": "Cucumber"},
                {"id": "303", "value": "Generic"},
            ],
        },
        "customfield_10004": {"operations": ["set"], "schema": {"custom": MANUAL_STEPS}},
        "customfield_10201": {
            "operations": ["set"],
            "schema": {"custom": CUCUMBER_TYPE},
            "allowedValues": [
                {"id": "401", "value": "Scenario"},
                {"id": "402", "value": "Scenario Outline"},
            ],
        },
        "customfield_10202": {"operations": ["set"], "schema": {"custom": SCENARIO}},
    }
    for name, value in overrides.items():
        if value is None:
            fields.pop(name, None)
        else:
            fields[name] = value
    return fields


def _issue(
    key: str = "QA-7",
    *,
    kind: str | None = "Manual",
    steps: object = None,
    scenario: object = None,
    cucumber_type: str | None = None,
    links: tuple[object, ...] = (),
    components: tuple[str, ...] = (),
    preconditions: object = None,
    edit: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": "10007",
        "key": key,
        "fields": {
            "summary": "Login works",
            "issuetype": {"id": "10100", "name": "Test"},
            "components": [{"name": name} for name in components],
            "issuelinks": list(links),
            "customfield_10200": {"id": "301", "value": kind} if kind else None,
            "customfield_10004": steps,
            "customfield_10201": {"value": cucumber_type} if cucumber_type else None,
            "customfield_10202": scenario,
            "customfield_10300": preconditions,
        },
        "schema": {
            "summary": {"type": "string", "system": "summary"},
            "customfield_10200": {"type": "option", "custom": TEST_TYPE},
            "customfield_10004": {"type": "any", "custom": MANUAL_STEPS},
            "customfield_10201": {"type": "option", "custom": CUCUMBER_TYPE},
            "customfield_10202": {"type": "string", "custom": SCENARIO},
            "customfield_10300": {"type": "array", "custom": PRECONDITIONS},
        },
        "editmeta": {"fields": _editmeta() if edit is None else edit},
    }


def _link(name: str, *, outward: str | None = None, inward: str | None = None) -> object:
    link: dict[str, object] = {"type": {"name": name, "inward": "x", "outward": "y"}}
    if outward:
        link["outwardIssue"] = {"key": outward}
    if inward:
        link["inwardIssue"] = {"key": inward}
    return link


def _steps(*rows: Mapping[str, object]) -> dict[str, object]:
    return {"steps": [{"id": n, "index": n, "fields": dict(r)} for n, r in enumerate(rows, 1)]}


class _Jira:
    def __init__(
        self,
        *issues: dict[str, object],
        puts: tuple[Reply, ...] = (),
        after_put: dict[str, object] | None = None,
        link_types: object = None,
    ) -> None:
        self.issues = {str(issue["key"]): issue for issue in issues}
        self.puts = list(puts)
        self.after_put = after_put
        self.link_types = (
            {"issueLinkTypes": [{"id": "1", "name": "Test"}, {"id": "2", "name": "Blocks"}]}
            if link_types is None
            else link_types
        )
        self.put_bodies: list[dict[str, object]] = []
        self.reads: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        path = request.url.path
        if path == f"{API}/issueLinkType":
            return httpx.Response(200, json=self.link_types)
        key = path.removeprefix(f"{API}/issue/")
        if request.method == "GET":
            self.reads.append(request)
            issue = self.issues.get(key)
            return httpx.Response(200, json=issue) if issue else httpx.Response(404)
        assert request.method == "PUT"
        self.put_bodies.append(json.loads(request.content))
        response = self.puts.pop(0)(request) if self.puts else httpx.Response(204)
        if response.is_success and self.after_put is not None:
            self.issues[key] = self.after_put
        return response


def _importer(jira: _Jira) -> XrayServerImporter:
    return XrayServerImporter(
        base_url=BASE_URL,
        token=TOKEN,
        project_key="QA",
        link_type="Test",
        cache=XraySchemaCache(),
        transport=httpx.MockTransport(jira),
    )


def _status(code: int) -> Reply:
    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json={"errorMessages": [f"bad {TOKEN}"]})

    return reply


def _raise(error: Exception) -> Reply:
    def reply(request: httpx.Request) -> httpx.Response:
        raise error

    return reply


# --- details and capabilities -------------------------------------------------


def test_manual_test_details_are_read_with_links_steps_and_edit_capabilities() -> None:
    jira = _Jira(
        _issue(
            steps=_steps(
                {"Action": "Open login", "Data": "", "Expected Result": "Form"},
                {"action": "Submit", "data": "user=ann", "expected result": None},
            ),
            links=(_link("Test", outward="ABC-1"), _link("Blocks", inward="ABC-2")),
            components=("UI",),
            preconditions=["QA-90", "QA-91"],
        )
    )

    result = _importer(jira).test_details(["QA-7"])

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
            preconditions=2,
            editable=ALL_EDITABLE,
            allowed_components=frozenset({"UI", "API"}),
        )
    }
    assert jira.reads[0].url.params["expand"] == "schema,editmeta"


def test_cucumber_outline_details_keep_the_scenario_type_and_gherkin() -> None:
    jira = _Jira(
        _issue(kind="Cucumber", scenario="Given a <x>", cucumber_type="Scenario Outline")
    )

    details = _importer(jira).test_details(["QA-7"]).found["QA-7"]

    assert (details.kind, details.scenario_type, details.gherkin) == (
        "cucumber",
        "scenario_outline",
        "Given a <x>",
    )
    assert details.steps == ()


def test_generic_test_type_is_reported_as_other() -> None:
    jira = _Jira(_issue(kind="Generic"))

    assert _importer(jira).test_details(["QA-7"]).found["QA-7"].kind == "other"


def test_missing_key_is_neither_found_nor_unreadable_and_malformed_rows_are_unreadable() -> None:
    jira = _Jira(
        _issue("QA-1", steps={"steps": "nope"}),
        _issue("QA-2", kind=None),
        _issue("QA-3", kind="Cucumber", scenario="Given a", cucumber_type="Weird"),
        _issue("QA-4"),
    )

    result = _importer(jira).test_details(["QA-1", "QA-2", "QA-3", "QA-4", "QA-9"])

    assert result.unreadable == {"QA-1", "QA-2", "QA-3"}
    assert set(result.found) == {"QA-4"}


@pytest.mark.parametrize(
    ("overrides", "lost"),
    [
        ({"summary": {"operations": ["add"]}}, {"summary"}),
        ({"issuelinks": None}, {"story_link"}),
        ({"components": {"operations": ["set"]}}, {"component"}),
        (
            {
                "customfield_10201": {
                    "operations": ["set"],
                    "schema": {"custom": CUCUMBER_TYPE},
                    "allowedValues": [{"id": "401", "value": "Scenario"}],
                }
            },
            {"scenario_type", "test_type"},
        ),
        ({"customfield_10004": None}, {"steps", "test_type"}),
        ({"customfield_10202": None}, {"gherkin", "scenario_type", "test_type"}),
    ],
    ids=[
        "summary-add-only",
        "no-links",
        "components-set-only",
        "no-outline",
        "no-steps",
        "no-scenario",
    ],
)
def test_editable_follows_editmeta_operations_and_options(
    overrides: dict[str, object], lost: set[str]
) -> None:
    jira = _Jira(_issue(edit=_editmeta(**overrides)))

    details = _importer(jira).test_details(["QA-7"]).found["QA-7"]

    assert details.editable == ALL_EDITABLE - lost


def test_details_transport_failure_raises() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    importer = XrayServerImporter(
        base_url=BASE_URL,
        token=TOKEN,
        project_key="QA",
        link_type="Test",
        cache=XraySchemaCache(),
        transport=httpx.MockTransport(down),
    )

    with pytest.raises(ConnectorUnavailableError):
        importer.test_details(["QA-7"])


@pytest.mark.parametrize(
    ("link_types", "expected"),
    [(None, True), ({"issueLinkTypes": [{"id": "2", "name": "Blocks"}]}, False)],
    ids=["present", "absent"],
)
def test_capabilities_confirm_the_configured_link_type(link_types: object, expected: bool) -> None:
    jira = _Jira(link_types=link_types)

    assert _importer(jira).capabilities() == XrayUpdateCapabilities(
        jira_fields=True, story_link_type=expected
    )


# --- update_test ----------------------------------------------------------------

_MANUAL_STEPS = (XrayTestStep(action="Open login", expected="Form"),)
_STEPS_VALUE = {
    "steps": [
        {"index": 1, "fields": {"action": "Open login", "data": "", "expected result": "Form"}}
    ]
}


def _patch(**members: object) -> XrayTestPatch:
    return XrayTestPatch(key="QA-7", issue_id="10007", **members)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("patch", "body"),
    [
        (_patch(summary="New name"), {"fields": {"summary": "New name"}}),
        (
            _patch(definition=ManualDefinition(_MANUAL_STEPS)),
            {"fields": {"customfield_10004": _STEPS_VALUE}},
        ),
        (
            _patch(definition=CucumberDefinition("Given b")),
            {"fields": {"customfield_10202": "Given b"}},
        ),
        (
            _patch(
                scenario_type_change=("scenario", "scenario_outline"),
                definition=CucumberDefinition("Given <b>", outline=True),
            ),
            {"fields": {"customfield_10201": {"id": "402"}, "customfield_10202": "Given <b>"}},
        ),
        (
            _patch(add_component="UI", add_story_link=IssueLinkRef("Test", "outward", "ABC-1")),
            {
                "update": {
                    "components": [{"add": {"name": "UI"}}],
                    "issuelinks": [
                        {"add": {"type": {"name": "Test"}, "outwardIssue": {"key": "ABC-1"}}}
                    ],
                }
            },
        ),
    ],
    ids=["summary", "steps", "gherkin", "outline", "component-and-link"],
)
def test_put_body_holds_only_the_patch_members(patch: XrayTestPatch, body: object) -> None:
    jira = _Jira(_issue(kind="Cucumber", scenario="Given a", cucumber_type="Scenario"))

    _importer(jira).update_test(patch)

    assert jira.put_bodies == [body]


def test_manual_to_cucumber_switch_writes_the_target_and_clears_the_steps() -> None:
    after = _issue(kind="Cucumber", scenario="Given b", cucumber_type="Scenario", steps={"steps": []})
    jira = _Jira(_issue(steps=_STEPS_VALUE), after_put=after)

    _importer(jira).update_test(
        _patch(kind_change=("manual", "cucumber"), definition=CucumberDefinition("Given b"))
    )

    assert jira.put_bodies == [
        {
            "fields": {
                "customfield_10200": {"id": "302"},
                "customfield_10201": {"id": "401"},
                "customfield_10202": "Given b",
                "customfield_10004": {"steps": []},
            }
        }
    ]


def test_cucumber_to_manual_switch_writes_the_steps_and_clears_the_scenario() -> None:
    after = _issue(steps=_STEPS_VALUE, scenario="")
    jira = _Jira(
        _issue(kind="Cucumber", scenario="Given a", cucumber_type="Scenario"), after_put=after
    )

    _importer(jira).update_test(
        _patch(kind_change=("cucumber", "manual"), definition=ManualDefinition(_MANUAL_STEPS))
    )

    assert jira.put_bodies == [
        {
            "fields": {
                "customfield_10200": {"id": "301"},
                "customfield_10004": _STEPS_VALUE,
                "customfield_10202": "",
            }
        }
    ]


@pytest.mark.parametrize(
    "after",
    [
        _issue(kind="Cucumber", scenario="Given b", cucumber_type="Scenario", steps=_STEPS_VALUE),
        _issue(steps=_STEPS_VALUE),
        _issue(kind="Cucumber", scenario="Given other", cucumber_type="Scenario"),
    ],
    ids=["old-steps-kept", "kind-unchanged", "wrong-definition"],
)
def test_kind_switch_that_does_not_read_back_is_not_confirmed(after: dict[str, object]) -> None:
    jira = _Jira(_issue(steps=_STEPS_VALUE), after_put=after)

    with pytest.raises(XrayUpdateNotConfirmedError):
        _importer(jira).update_test(
            _patch(kind_change=("manual", "cucumber"), definition=CucumberDefinition("Given b"))
        )


def test_kind_switch_read_back_failure_is_not_confirmed() -> None:
    jira = _Jira(_issue(steps=_STEPS_VALUE))
    jira.after_put = {"key": "QA-7"}

    with pytest.raises(XrayUpdateNotConfirmedError):
        _importer(jira).update_test(
            _patch(kind_change=("manual", "cucumber"), definition=CucumberDefinition("Given b"))
        )


def test_change_that_is_no_longer_editable_is_rejected_without_a_put() -> None:
    jira = _Jira(_issue(edit=_editmeta(summary=None)))

    with pytest.raises(XrayUpdateRejectedError):
        _importer(jira).update_test(_patch(summary="New"))
    assert jira.put_bodies == []


def test_missing_test_is_rejected_without_a_put() -> None:
    jira = _Jira()

    with pytest.raises(XrayUpdateRejectedError):
        _importer(jira).update_test(_patch(summary="New"))
    assert jira.put_bodies == []


@pytest.mark.parametrize("code", [400, 403, 404])
def test_put_refused_by_jira_is_rejected(code: int) -> None:
    jira = _Jira(_issue(), puts=(_status(code),))

    with pytest.raises(XrayUpdateRejectedError) as caught:
        _importer(jira).update_test(_patch(summary="New"))
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize(
    "reply",
    [_status(500), _status(502), _raise(httpx.ReadTimeout("slow"))],
    ids=["500", "502", "timeout"],
)
def test_put_with_unknown_outcome_is_uncertain(reply: Reply) -> None:
    jira = _Jira(_issue(), puts=(reply,))

    with pytest.raises(XrayUpdateUncertainError) as caught:
        _importer(jira).update_test(_patch(summary="New"))
    assert caught.value.partial is False


def test_put_auth_failure_raises_auth_error() -> None:
    jira = _Jira(_issue(), puts=(_status(401),))

    with pytest.raises(ConnectorAuthError):
        _importer(jira).update_test(_patch(summary="New"))


def test_put_answered_with_200_and_a_body_is_accepted() -> None:
    jira = _Jira(_issue(), puts=(lambda request: httpx.Response(200, json={}),))

    _importer(jira).update_test(_patch(summary="New"))

    assert len(jira.put_bodies) == 1
