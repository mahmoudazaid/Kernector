"""XrayServerImporter create behaviour through httpx.MockTransport; no live Jira."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace

import httpx
import pytest

from domain.errors import ConnectorAuthError, ConnectorError, ConnectorUnavailableError
from domain.test_management.xray import (
    IssueLookupResult,
    JiraIssueSummary,
    XrayImportResult,
    XrayRequiredFieldsError,
    XrayTestSpec,
    XrayTestStep,
)
from infrastructure.connectors.xray.schema import XraySchemaCache
from infrastructure.connectors.xray.server import XrayServerImporter
from test.infrastructure.connectors.xray.test_server_schema import (
    API,
    BASE_URL,
    TEST_TYPE,
    TOKEN,
    _field,
    xray_fields,
)

_MANUAL = XrayTestSpec(
    title="Login works",
    kind="manual",
    preconditions="User exists",
    steps=(XrayTestStep(action="Open login"), XrayTestStep(action="Submit", expected="Home")),
    link_issue_key="QA-7",
)
_CUCUMBER = XrayTestSpec(title="Logout", kind="cucumber", gherkin="Given a session\nWhen I log out")

CreateReply = Callable[[httpx.Request], httpx.Response]


def _created(key: str) -> CreateReply:
    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"id": "1", "key": key, "self": "x"})

    return reply


def _status(code: int) -> CreateReply:
    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json={"errors": {"customfield_10004": f"bad {TOKEN}"}})

    return reply


class _Jira:
    def __init__(self, *creates: CreateReply, fields=None, source=None) -> None:
        self.creates = list(creates)
        self.fields = xray_fields() if fields is None else fields
        self.source: dict[str, object] = source or {}
        self.discoveries = 0
        self.source_requests: list[httpx.Request] = []
        self.create_bodies: list[dict[str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"{API}/issue/createmeta/QA/issuetypes":
            self.discoveries += 1
            return httpx.Response(200, json={"values": [{"id": "10100", "name": "Test"}]})
        if path == f"{API}/issue/createmeta/QA/issuetypes/10100":
            return httpx.Response(200, json={"values": self.fields, "isLast": True})
        if request.method == "GET" and path == f"{API}/issue/QA-7":
            self.source_requests.append(request)
            return httpx.Response(200, json={"key": "QA-7", "fields": self.source})
        if request.method == "GET" and path.startswith(f"{API}/issue/"):
            return httpx.Response(404)
        assert request.method == "POST"
        assert path == f"{API}/issue"
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        self.create_bodies.append(json.loads(request.content))
        return self.creates.pop(0)(request)


def _importer(handler, cache: XraySchemaCache | None = None) -> XrayServerImporter:
    return XrayServerImporter(
        base_url=BASE_URL,
        token=TOKEN,
        project_key="QA",
        link_type="Test",
        cache=cache or XraySchemaCache(),
        transport=httpx.MockTransport(handler),
    )


def test_manual_spec_is_created_as_a_jira_test_issue_with_xray_fields() -> None:
    jira = _Jira(_created("QA-101"))

    result = _importer(jira).import_tests([_MANUAL])

    assert result == XrayImportResult(created_keys=("QA-101",), failed_count=0)
    assert jira.create_bodies == [
        {
            "fields": {
                "project": {"key": "QA"},
                "summary": "Login works",
                "issuetype": {"id": "10100"},
                "description": "User exists",
                "customfield_10200": {"id": "301"},
                "customfield_10004": {
                    "steps": [
                        {
                            "index": 1,
                            "fields": {"action": "Open login", "data": "", "expected result": ""},
                        },
                        {
                            "index": 2,
                            "fields": {"action": "Submit", "data": "", "expected result": "Home"},
                        },
                    ]
                },
            },
            "update": {
                "issuelinks": [
                    {"add": {"type": {"name": "Test"}, "outwardIssue": {"key": "QA-7"}}}
                ]
            },
        }
    ]


def test_cucumber_spec_sets_test_type_scenario_type_and_scenario() -> None:
    jira = _Jira(_created("QA-102"))

    _importer(jira).import_tests([_CUCUMBER])

    assert jira.create_bodies == [
        {
            "fields": {
                "project": {"key": "QA"},
                "summary": "Logout",
                "issuetype": {"id": "10100"},
                "customfield_10200": {"id": "302"},
                "customfield_10201": {"id": "401"},
                "customfield_10202": "Given a session\nWhen I log out",
            }
        }
    ]


def test_rejected_creates_are_counted_and_the_batch_continues() -> None:
    jira = _Jira(_created("QA-1"), _status(400), _created("QA-3"))

    result = _importer(jira).import_tests([_CUCUMBER, _CUCUMBER, _CUCUMBER])

    assert result == XrayImportResult(created_keys=("QA-1", "QA-3"), failed_count=1)


def test_auth_failure_before_any_create_raises_secret_free() -> None:
    jira = _Jira(_status(401))

    with pytest.raises(ConnectorAuthError) as caught:
        _importer(jira).import_tests([_MANUAL])

    rendered = " ".join(str(e) for e in (caught.value, caught.value.__cause__) if e)
    assert TOKEN not in rendered
    assert "customfield" not in rendered


@pytest.mark.parametrize("code", [429, 500, 503])
def test_unavailable_first_create_raises_without_retry(code: int) -> None:
    jira = _Jira(_status(code))

    with pytest.raises(ConnectorUnavailableError):
        _importer(jira).import_tests([_MANUAL, _MANUAL])

    assert len(jira.create_bodies) == 1


def test_ambiguous_failure_after_a_create_stops_with_partial_result() -> None:
    jira = _Jira(_created("QA-1"), _status(503))

    result = _importer(jira).import_tests([_MANUAL, _MANUAL, _MANUAL])

    assert result == XrayImportResult(created_keys=("QA-1",), failed_count=2)
    assert len(jira.create_bodies) == 2


def test_stale_cached_schema_is_rediscovered_once_and_the_create_retried() -> None:
    cache = XraySchemaCache()
    old_fields = xray_fields()
    old_fields[5] = _field(
        "customfield_10200",
        custom=TEST_TYPE,
        allowedValues=[{"id": "999", "value": "Manual"}, {"id": "302", "value": "Cucumber"}],
    )
    _importer(_Jira(fields=old_fields), cache).schema()
    jira = _Jira(_status(400), _created("QA-9"), _status(400))

    result = _importer(jira, cache).import_tests([_MANUAL, _MANUAL])

    assert result == XrayImportResult(created_keys=("QA-9",), failed_count=1)
    assert jira.discoveries == 1
    first, retry, second = jira.create_bodies
    assert first["fields"]["customfield_10200"] == {"id": "999"}
    assert retry["fields"]["customfield_10200"] == {"id": "301"}
    assert second["fields"]["customfield_10200"] == {"id": "301"}


def test_freshly_discovered_schema_rejection_is_not_retried() -> None:
    jira = _Jira(_status(400))

    result = _importer(jira).import_tests([_MANUAL])

    assert result == XrayImportResult(created_keys=(), failed_count=1)
    assert jira.discoveries == 1
    assert len(jira.create_bodies) == 1


def test_spec_whose_kind_is_not_ready_is_counted_failed_without_a_request() -> None:
    fields = [f for f in xray_fields() if f["fieldId"] != "customfield_10202"]
    jira = _Jira(_created("QA-1"), fields=fields)

    result = _importer(jira).import_tests([_MANUAL, _CUCUMBER])

    assert result == XrayImportResult(created_keys=("QA-1",), failed_count=1)
    assert len(jira.create_bodies) == 1


_COMPONENTS = _field(
    "components",
    required=True,
    hasDefaultValue=False,
    type_="array",
    name="Component/s",
    allowedValues=[{"id": "10", "name": "SD_WAN"}, {"id": "11", "name": "Core"}],
)
_SOURCED = replace(_CUCUMBER, source_issue_key="QA-7")


def test_required_field_is_inherited_from_the_source_issue_once_per_batch() -> None:
    jira = _Jira(
        _created("QA-1"),
        _created("QA-2"),
        fields=[*xray_fields(), _COMPONENTS],
        source={"components": [{"id": "10", "name": "SD_WAN", "self": "x"}]},
    )

    result = _importer(jira).import_tests([_SOURCED, _SOURCED])

    assert result.created_keys == ("QA-1", "QA-2")
    assert [body["fields"]["components"] for body in jira.create_bodies] == [
        [{"id": "10"}],
        [{"id": "10"}],
    ]
    (source_request,) = jira.source_requests
    assert source_request.url.params["fields"] == "components"


def test_source_value_outside_the_allowed_values_is_not_copied() -> None:
    jira = _Jira(
        fields=[*xray_fields(), _COMPONENTS],
        source={"components": [{"id": "99", "name": "Other project"}]},
    )

    with pytest.raises(XrayRequiredFieldsError) as caught:
        _importer(jira).import_tests([_SOURCED])

    assert caught.value.field_names == ("Component/s",)
    assert jira.create_bodies == []


def test_source_value_is_matched_to_an_allowed_value_by_name() -> None:
    jira = _Jira(
        _created("QA-1"),
        fields=[*xray_fields(), _COMPONENTS],
        source={"components": [{"id": "77", "name": "Core"}]},
    )

    _importer(jira).import_tests([_SOURCED])

    assert jira.create_bodies[0]["fields"]["components"] == [{"id": "11"}]


def test_unreadable_source_issue_falls_back_to_naming_the_missing_fields() -> None:
    jira = _Jira(fields=[*xray_fields(), _COMPONENTS])
    hidden = replace(_CUCUMBER, source_issue_key="QA-404")

    with pytest.raises(XrayRequiredFieldsError) as caught:
        _importer(jira).import_tests([hidden])

    assert caught.value.field_names == ("Component/s",)


def test_free_form_source_values_are_copied_as_is() -> None:
    labels = _field("labels", required=True, type_="array", name="Labels")
    jira = _Jira(_created("QA-1"), fields=[*xray_fields(), labels], source={"labels": ["sdwan"]})

    _importer(jira).import_tests([_SOURCED])

    assert jira.create_bodies[0]["fields"]["labels"] == ["sdwan"]


def test_required_field_with_a_single_allowed_value_uses_it_without_a_source() -> None:
    team = _field(
        "customfield_500",
        required=True,
        type_="option",
        name="Team",
        allowedValues=[{"id": "7", "value": "Platform"}],
    )
    jira = _Jira(_created("QA-1"), fields=[*xray_fields(), team])

    _importer(jira).import_tests([_CUCUMBER])

    assert jira.create_bodies[0]["fields"]["customfield_500"] == {"id": "7"}
    assert jira.source_requests == []


def test_unresolvable_required_fields_fail_by_name_before_any_create() -> None:
    fields = [
        *xray_fields(),
        _COMPONENTS,
        _field("customfield_600", required=True, name="Squad"),
        _field("priority", required=True, hasDefaultValue=True),
    ]
    jira = _Jira(fields=fields)

    with pytest.raises(XrayRequiredFieldsError) as caught:
        _importer(jira).import_tests([_CUCUMBER, _CUCUMBER])

    assert caught.value.field_names == ("Component/s", "Squad")
    assert jira.create_bodies == []


def test_requested_link_that_cannot_be_sent_is_rejected_without_a_request() -> None:
    fields = [f for f in xray_fields() if f["fieldId"] != "issuelinks"]
    jira = _Jira(fields=fields)

    result = _importer(jira).import_tests([_MANUAL])

    assert result == XrayImportResult(created_keys=(), failed_count=1)
    assert jira.create_bodies == []


def test_requested_link_without_a_configured_link_type_is_rejected() -> None:
    jira = _Jira()
    importer = XrayServerImporter(
        base_url=BASE_URL,
        token=TOKEN,
        project_key="QA",
        link_type=" ",
        cache=XraySchemaCache(),
        transport=httpx.MockTransport(jira),
    )

    assert importer.import_tests([_MANUAL]).failed_count == 1
    assert jira.create_bodies == []


def test_configured_component_overrides_required_component_resolution() -> None:
    jira = _Jira(
        _created("QA-1"),
        fields=[*xray_fields(), _COMPONENTS],
        source={"components": [{"id": "10", "name": "SD_WAN"}]},
    )

    _importer(jira).import_tests([replace(_SOURCED, component="Checkout")])

    assert jira.create_bodies[0]["fields"]["components"] == [{"name": "Checkout"}]
    assert jira.source_requests == []


def test_configured_component_is_sent_when_not_required() -> None:
    jira = _Jira(_created("QA-1"))

    _importer(jira).import_tests([replace(_CUCUMBER, component="Checkout")])

    assert jira.create_bodies[0]["fields"]["components"] == [{"name": "Checkout"}]


def test_without_a_configured_component_a_required_single_component_is_used() -> None:
    only = _field(
        "components",
        required=True,
        type_="array",
        name="Component/s",
        allowedValues=[{"id": "10", "name": "SD_WAN"}],
    )
    jira = _Jira(_created("QA-1"), fields=[*xray_fields(), only])

    _importer(jira).import_tests([_CUCUMBER])

    assert jira.create_bodies[0]["fields"]["components"] == [{"id": "10"}]


def test_outline_spec_uses_the_scenario_outline_option() -> None:
    jira = _Jira(_created("QA-1"))

    _importer(jira).import_tests([replace(_CUCUMBER, outline=True)])

    assert jira.create_bodies[0]["fields"]["customfield_10201"] == {"id": "402"}


def test_outline_without_a_scenario_outline_option_is_rejected_without_a_request() -> None:
    fields = xray_fields()
    fields[7] = _field(
        "customfield_10201",
        custom="com.xpandit.plugins.xray:automated-test-type-custom-field",
        allowedValues=[{"id": "401", "value": "Scenario"}],
    )
    jira = _Jira(fields=fields)
    importer = _importer(jira)

    result = importer.import_tests([replace(_CUCUMBER, outline=True)])

    assert importer.schema().supports_cucumber_outline is False
    assert result == XrayImportResult(created_keys=(), failed_count=1)
    assert jira.create_bodies == []


class _Lookup:
    """Jira answering issue reads for the lookup port."""

    def __init__(self, issues: dict[str, object], *, status: int | None = None) -> None:
        self.issues = issues
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"{API}/issue/createmeta/QA/issuetypes":
            return httpx.Response(200, json={"values": [{"id": "10100", "name": "Test"}]})
        if path == f"{API}/issue/createmeta/QA/issuetypes/10100":
            return httpx.Response(200, json={"values": xray_fields(), "isLast": True})
        self.requests.append(request)
        if self.status is not None:
            return httpx.Response(self.status, text=f"vendor {TOKEN}")
        key = path.rsplit("/", 1)[-1]
        if key not in self.issues:
            return httpx.Response(404)
        return httpx.Response(200, json=self.issues[key])


def _issue(key: str, summary: str, type_id: str, type_name: str, **fields) -> dict:
    return {
        "key": key,
        "fields": {"summary": summary, "issuetype": {"id": type_id, "name": type_name}, **fields},
    }


def _link(issue: dict, direction: str = "outwardIssue") -> dict:
    return {"id": "1", "type": {"name": "Test"}, direction: issue}


def test_find_issues_reads_each_key_and_reports_404_as_missing() -> None:
    jira = _Lookup(
        {
            "QA-5": _issue("QA-5", "Login", "10100", "Test"),
            "ABC-1": _issue("ABC-1", "Story", "10001", "Story"),
        }
    )

    result = _importer(jira).find_issues(["QA-5", "ABC-1", "ABC-9"])

    assert result == IssueLookupResult(
        found={
            "QA-5": JiraIssueSummary("QA-5", "Login", "10100", "Test", True),
            "ABC-1": JiraIssueSummary("ABC-1", "Story", "10001", "Story", False),
        },
        missing=frozenset({"ABC-9"}),
    )
    assert {r.url.params["fields"] for r in jira.requests} == {"issuetype,summary"}


def test_find_issues_is_test_follows_the_discovered_type_id_not_the_name() -> None:
    jira = _Lookup({"QA-5": _issue("QA-5", "Login", "555", "Test")})

    assert _importer(jira).find_issues(["QA-5"]).found["QA-5"].is_test is False


def test_find_issues_fails_closed_on_errors_and_malformed_answers() -> None:
    with pytest.raises(ConnectorUnavailableError):
        _importer(_Lookup({}, status=500)).find_issues(["QA-5"])
    with pytest.raises(ConnectorAuthError):
        _importer(_Lookup({}, status=401)).find_issues(["QA-5"])
    with pytest.raises(ConnectorError):
        _importer(_Lookup({"QA-5": {"key": "QA-5", "fields": {"summary": 3}}})).find_issues(
            ["QA-5"]
        )


def test_linked_tests_keeps_only_test_issues_in_either_direction() -> None:
    story = _issue(
        "ABC-1",
        "Story",
        "10001",
        "Story",
        issuelinks=[
            _link(_issue("QA-5", "Login", "10100", "Test")),
            _link(_issue("QA-6", "Logout", "10100", "Test"), "inwardIssue"),
            _link(_issue("ABC-2", "Other", "10001", "Story")),
        ],
    )
    jira = _Lookup({"ABC-1": story})

    linked = _importer(jira).linked_tests("ABC-1")

    assert [t.key for t in linked] == ["QA-5", "QA-6"]
    assert jira.requests[0].url.params["fields"] == "issuelinks"


def test_linked_tests_raises_on_a_malformed_link() -> None:
    story = _issue("ABC-1", "Story", "10001", "Story", issuelinks=[{"id": "1"}])

    with pytest.raises(ConnectorError):
        _importer(_Lookup({"ABC-1": story})).linked_tests("ABC-1")
