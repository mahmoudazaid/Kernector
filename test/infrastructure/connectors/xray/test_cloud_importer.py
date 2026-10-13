"""XrayCloudImporter create behaviour through httpx.MockTransport; no live Xray."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import replace

import httpx
import pytest

from domain.errors import ConnectorAuthError, ConnectorError, ConnectorUnavailableError
from domain.test_management.xray import (
    IssueLookupResult,
    JiraIssueSummary,
    XrayCreateWarning,
    XrayImportResult,
    XrayTestSpec,
    XrayTestStep,
)
from infrastructure.connectors.xray.cloud import XrayCloudImporter
from infrastructure.connectors.xray.schema import XraySchemaCache

BASE_URL = "https://xray.example.test"
CLIENT_SECRET = "cloud-client-secret-XYZ"
TOKEN = "xray-bearer-token-ABC"

_TEST_TYPES = [
    {"id": "t-steps", "name": "Exploratory Steps", "kind": "Steps"},
    {"id": "t-manual", "name": "Manual", "kind": "Steps"},
    {"id": "t-cucumber", "name": "Cucumber", "kind": "Gherkin"},
]

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
        return httpx.Response(
            200,
            json={"data": {"createTest": {"test": {"issueId": "1", "jira": {"key": key}}}}},
        )

    return reply


def _rejected(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"errors": [{"message": f"customfield_1 invalid {TOKEN}"}], "data": None},
    )


def _status(code: int) -> CreateReply:
    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, text=f"vendor body {CLIENT_SECRET}")

    return reply


class _Xray:
    def __init__(self, *creates: CreateReply, test_types=_TEST_TYPES) -> None:
        self.creates = list(creates)
        self.test_types = test_types
        self.discoveries = 0
        self.create_bodies: list[dict[str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/authenticate":
            return httpx.Response(200, json=TOKEN)
        body = json.loads(request.content)
        if "getProjectSettings" in body["query"]:
            self.discoveries += 1
            settings = {"testTypeSettings": {"testTypes": self.test_types}}
            return httpx.Response(200, json={"data": {"getProjectSettings": settings}})
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        self.create_bodies.append(body)
        return self.creates.pop(0)(request)


def _importer(handler, cache: XraySchemaCache | None = None) -> XrayCloudImporter:
    return XrayCloudImporter(
        base_url=BASE_URL,
        client_id="cloud-client-id",
        client_secret=CLIENT_SECRET,
        project_key="QA",
        link_type="Test",
        cache=cache or XraySchemaCache(),
        transport=httpx.MockTransport(handler),
    )


def test_manual_spec_is_created_with_steps_link_and_preconditions() -> None:
    xray = _Xray(_created("QA-101"))

    result = _importer(xray).import_tests([_MANUAL])

    assert result == XrayImportResult(created_keys=("QA-101",), failed_count=0)
    [body] = xray.create_bodies
    assert "createTest" in body["query"]
    assert body["variables"] == {
        "testType": {"id": "t-manual"},
        "steps": [
            {"action": "Open login", "data": "", "result": ""},
            {"action": "Submit", "data": "", "result": "Home"},
        ],
        "jira": {
            "fields": {
                "summary": "Login works",
                "project": {"key": "QA"},
                "description": "User exists",
            },
            "update": {
                "issuelinks": [
                    {"add": {"type": {"name": "Test"}, "outwardIssue": {"key": "QA-7"}}}
                ]
            },
        },
    }


def test_cucumber_spec_is_created_with_gherkin_only() -> None:
    xray = _Xray(_created("QA-102"))

    _importer(xray).import_tests([_CUCUMBER])

    [body] = xray.create_bodies
    assert body["variables"] == {
        "testType": {"id": "t-cucumber"},
        "gherkin": "Given a session\nWhen I log out",
        "jira": {"fields": {"summary": "Logout", "project": {"key": "QA"}}},
    }


def test_rejected_creates_are_counted_and_the_batch_continues() -> None:
    xray = _Xray(_created("QA-1"), _rejected, _created("QA-3"))

    result = _importer(xray).import_tests([_CUCUMBER, _CUCUMBER, _CUCUMBER])

    assert result == XrayImportResult(created_keys=("QA-1", "QA-3"), failed_count=1)


def test_authentication_rejection_raises_auth_error_before_any_create() -> None:
    xray = _Xray()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/authenticate":
            return httpx.Response(401, text=f"bad {CLIENT_SECRET}")
        return xray(request)

    with pytest.raises(ConnectorAuthError) as caught:
        _importer(handler).import_tests([_MANUAL])

    assert xray.create_bodies == []
    _assert_secret_free(caught.value)


@pytest.mark.parametrize("code", [429, 500, 503])
def test_unavailable_first_create_raises_without_retry(code: int) -> None:
    xray = _Xray(_status(code))

    with pytest.raises(ConnectorUnavailableError) as caught:
        _importer(xray).import_tests([_MANUAL, _MANUAL])

    assert len(xray.create_bodies) == 1
    _assert_secret_free(caught.value)


def test_ambiguous_failure_after_a_create_stops_and_reports_partial_result() -> None:
    xray = _Xray(_created("QA-1"), _status(503))

    result = _importer(xray).import_tests([_MANUAL, _MANUAL, _MANUAL])

    assert result == XrayImportResult(created_keys=("QA-1",), failed_count=2)
    assert len(xray.create_bodies) == 2


def test_auth_failure_after_a_create_reports_partial_result() -> None:
    xray = _Xray(_created("QA-1"), _status(401), _status(401))

    result = _importer(xray).import_tests([_MANUAL, _MANUAL])

    assert result == XrayImportResult(created_keys=("QA-1",), failed_count=1)
    assert len(xray.create_bodies) == 3


def test_expired_token_is_refreshed_once_and_the_request_retried() -> None:
    tokens = iter(["token-1", "token-2", "token-3"])
    state = {"current": "", "auth_calls": 0, "valid": "token-1"}
    keys = iter(["QA-1", "QA-2", "QA-3"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/authenticate":
            state["auth_calls"] += 1
            state["current"] = next(tokens)
            return httpx.Response(200, json=state["current"])
        if request.headers["Authorization"] != f"Bearer {state['valid']}":
            return httpx.Response(401, text="expired")
        body = json.loads(request.content)
        if "getProjectSettings" in body["query"]:
            settings = {"testTypeSettings": {"testTypes": _TEST_TYPES}}
            return httpx.Response(200, json={"data": {"getProjectSettings": settings}})
        return _created(next(keys))(request)

    importer = _importer(handler)
    assert importer.import_tests([_MANUAL]).created_keys == ("QA-1",)

    state["valid"] = "token-2"
    assert importer.import_tests([_MANUAL]).created_keys == ("QA-2",)
    assert importer.import_tests([_MANUAL]).created_keys == ("QA-3",)
    assert state["auth_calls"] == 2


def test_fresh_token_rejected_with_401_is_not_refreshed_again() -> None:
    auth_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        if request.url.path == "/api/v2/authenticate":
            auth_calls += 1
            return httpx.Response(200, json=TOKEN)
        return httpx.Response(401, text=f"vendor body {CLIENT_SECRET}")

    with pytest.raises(ConnectorAuthError) as caught:
        _importer(handler).import_tests([_MANUAL])

    assert auth_calls == 1
    _assert_secret_free(caught.value)


def test_stale_cached_schema_is_rediscovered_once_and_the_create_retried() -> None:
    cache = XraySchemaCache()
    _importer(_Xray(test_types=[{"id": "t-old", "name": "Manual", "kind": "Steps"}]), cache).schema()
    xray = _Xray(_rejected, _created("QA-9"), _rejected)

    result = _importer(xray, cache).import_tests([_MANUAL, _MANUAL])

    assert result == XrayImportResult(created_keys=("QA-9",), failed_count=1)
    assert xray.discoveries == 1
    first, retry, second = xray.create_bodies
    assert first["variables"]["testType"] == {"id": "t-old"}
    assert retry["variables"]["testType"] == {"id": "t-manual"}
    assert second["variables"]["testType"] == {"id": "t-manual"}


def test_freshly_discovered_schema_rejection_is_not_retried() -> None:
    xray = _Xray(_rejected)

    result = _importer(xray).import_tests([_MANUAL])

    assert result == XrayImportResult(created_keys=(), failed_count=1)
    assert xray.discoveries == 1
    assert len(xray.create_bodies) == 1


def test_stale_retry_rejected_again_counts_one_failure_without_further_discovery() -> None:
    cache = XraySchemaCache()
    _importer(_Xray(), cache).schema()
    xray = _Xray(_rejected, _rejected)

    result = _importer(xray, cache).import_tests([_MANUAL])

    assert result == XrayImportResult(created_keys=(), failed_count=1)
    assert xray.discoveries == 1


def test_spec_without_a_discovered_type_is_counted_failed_without_a_request() -> None:
    xray = _Xray(_created("QA-1"), test_types=[{"id": "t-manual", "name": "Manual", "kind": "Steps"}])

    result = _importer(xray).import_tests([_MANUAL, _CUCUMBER])

    assert result == XrayImportResult(created_keys=("QA-1",), failed_count=1)
    assert len(xray.create_bodies) == 1


def test_malformed_create_response_after_a_create_is_ambiguous() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"createTest": {"test": None}}})

    xray = _Xray(_created("QA-1"), broken)

    result = _importer(xray).import_tests([_MANUAL, _MANUAL, _MANUAL])

    assert result == XrayImportResult(created_keys=("QA-1",), failed_count=2)


def test_malformed_first_create_response_raises() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"createTest": {"test": None}}})

    with pytest.raises(ConnectorError):
        _importer(_Xray(broken)).import_tests([_MANUAL])


def _assert_secret_free(error: BaseException) -> None:
    chain = [error, error.__cause__, error.__context__]
    rendered = " ".join(str(e) for e in chain if e is not None)
    for secret in (CLIENT_SECRET, TOKEN, "vendor body", "customfield"):
        assert secret not in rendered


def _created_with(key: str, *, warnings=(), scenario_type: str | None = None) -> CreateReply:
    def reply(request: httpx.Request) -> httpx.Response:
        test: dict[str, object] = {"issueId": "1", "jira": {"key": key}}
        if scenario_type is not None:
            test["scenarioType"] = scenario_type
        return httpx.Response(
            200,
            json={"data": {"createTest": {"test": test, "warnings": list(warnings)}}},
        )

    return reply


_LINKED = replace(_CUCUMBER, link_issue_key="ABC-1")


def test_configured_component_is_sent_in_the_jira_fields() -> None:
    xray = _Xray(_created("QA-1"))

    _importer(xray).import_tests([replace(_CUCUMBER, component="Checkout")])

    assert xray.create_bodies[0]["variables"]["jira"]["fields"]["components"] == [
        {"name": "Checkout"}
    ]


def test_link_warning_is_reported_as_an_unconfirmed_link() -> None:
    xray = _Xray(_created_with("QA-1", warnings=[f"link failed {TOKEN}"]))

    result = _importer(xray).import_tests([_LINKED])

    assert result == XrayImportResult(
        created_keys=("QA-1",),
        failed_count=0,
        warnings=(XrayCreateWarning("QA-1", "link_not_confirmed"),),
    )


def test_requested_link_without_a_link_type_is_rejected_without_a_request() -> None:
    xray = _Xray()
    importer = XrayCloudImporter(
        base_url=BASE_URL,
        client_id="cloud-client-id",
        client_secret=CLIENT_SECRET,
        project_key="QA",
        link_type="",
        cache=XraySchemaCache(),
        transport=httpx.MockTransport(xray),
    )

    assert importer.import_tests([_LINKED]) == XrayImportResult(created_keys=(), failed_count=1)
    assert xray.create_bodies == []


def test_outline_is_confirmed_from_the_returned_scenario_type() -> None:
    outline = replace(_CUCUMBER, outline=True, gherkin="Given <x>\n\nExamples:\n  | x |\n  | 1 |")
    xray = _Xray(
        _created_with("QA-1", scenario_type="scenario_outline"),
        _created_with("QA-2", scenario_type="scenario"),
    )

    importer = _importer(xray)
    confirmed = importer.import_tests([outline])
    downgraded = importer.import_tests([outline])

    assert confirmed.warnings == ()
    assert "scenarioType" in xray.create_bodies[0]["query"]
    assert xray.create_bodies[0]["variables"]["gherkin"] == outline.gherkin
    assert downgraded.warnings == (XrayCreateWarning("QA-2", "outline_not_confirmed"),)
    assert importer.schema().supports_cucumber_outline is True


def _jira(key: str, summary: str, type_id: str, type_name: str) -> dict[str, object]:
    return {
        "jira": {"key": key, "summary": summary, "issuetype": {"id": type_id, "name": type_name}}
    }


class _Search:
    """Xray Cloud answering getTests / getCoverableIssues searches."""

    def __init__(self, tests=(), coverable=(), *, page: int = 100, errors_for=()) -> None:
        self.tests = list(tests)
        self.coverable = list(coverable)
        self.page = page
        self.errors_for = set(errors_for)
        self.queries: list[dict[str, object]] = []
        self.total_override: int | None = None
        self.raw: dict[str, object] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/authenticate":
            return httpx.Response(200, json=TOKEN)
        body = json.loads(request.content)
        self.queries.append(body)
        if self.raw is not None:
            return httpx.Response(200, json=self.raw)
        jql = body["variables"]["jql"]
        jql_keys = set(re.findall(r"[A-Z][A-Z0-9_]*-[0-9]+", jql))
        if jql_keys & self.errors_for:
            return httpx.Response(200, json={"errors": [{"message": "bad key"}], "data": None})
        name = "getTests" if "getTests" in body["query"] else "getCoverableIssues"
        items = self.tests if name == "getTests" else self.coverable
        items = [i for i in items if i["jira"]["key"] in jql_keys or "linkedIssues" in jql]
        start = body["variables"]["start"]
        assert body["variables"]["limit"] <= 100
        page = items[start : start + self.page]
        total = len(items) if self.total_override is None else self.total_override
        return httpx.Response(
            200,
            json={"data": {name: {"total": total, "start": start, "results": page}}},
        )


def test_find_issues_reads_tests_and_coverable_issues_with_their_types() -> None:
    xray = _Search(
        tests=[_jira("QA-5", "Login", "10002", "Test")],
        coverable=[_jira("ABC-1", "Story", "10001", "Story")],
    )

    result = _importer(xray).find_issues(["QA-5", "ABC-1", "ABC-2"])

    assert result == IssueLookupResult(
        found={
            "QA-5": JiraIssueSummary("QA-5", "Login", "10002", "Test", True),
            "ABC-1": JiraIssueSummary("ABC-1", "Story", "10001", "Story", False),
        },
        missing=frozenset(),
    )
    assert all("key in (QA-5, ABC-1, ABC-2)" == q["variables"]["jql"] for q in xray.queries)


def test_find_issues_queries_keys_in_bounded_chunks() -> None:
    xray = _Search()
    keys = [f"ABC-{n}" for n in range(1, 121)]

    _importer(xray).find_issues(keys)

    assert len(xray.queries) == 6
    assert max(q["variables"]["jql"].count(",") + 1 for q in xray.queries) == 50


def test_find_issues_pages_until_total() -> None:
    xray = _Search(tests=[_jira(f"QA-{n}", "T", "1", "Test") for n in range(1, 6)], page=2)

    result = _importer(xray).find_issues([f"QA-{n}" for n in range(1, 6)])

    assert len(result.found) == 5
    assert [q["variables"]["start"] for q in xray.queries if "getTests" in q["query"]] == [0, 2, 4]


def test_search_beyond_the_page_bound_is_unavailable() -> None:
    xray = _Search(tests=[_jira(f"QA-{n}", "T", "1", "Test") for n in range(1, 30)], page=1)

    with pytest.raises(ConnectorUnavailableError):
        _importer(xray).linked_tests("ABC-1")

    assert len(xray.queries) == 20


def test_search_whose_pages_end_before_total_raises() -> None:
    xray = _Search(tests=[_jira("QA-1", "T", "1", "Test")])
    xray.total_override = 5

    with pytest.raises(ConnectorError):
        _importer(xray).linked_tests("ABC-1")


def test_chunk_errors_fall_back_per_key_and_failing_keys_stay_unresolved() -> None:
    xray = _Search(tests=[_jira("QA-5", "Login", "1", "Test")], errors_for=["ABC-404"])

    result = _importer(xray).find_issues(["QA-5", "ABC-404"])

    assert set(result.found) == {"QA-5"}
    assert result.missing == frozenset()


def test_refused_keys_in_several_chunks_stay_unresolved_without_failing_the_lookup() -> None:
    keys = [f"ABC-{n}" for n in range(1, 102)]
    bad = {"ABC-7", "ABC-57", "ABC-101"}
    xray = _Search(coverable=[_jira(k, "Story", "1", "Story") for k in keys], errors_for=bad)

    result = _importer(xray).find_issues(keys)

    assert set(result.found) == set(keys) - bad
    assert result.missing == frozenset()


def test_refused_chunk_splits_are_capped_and_leftover_keys_stay_unresolved() -> None:
    keys = [f"ABC-{n}" for n in range(1, 501)]
    xray = _Search(coverable=[_jira(k, "Story", "1", "Story") for k in keys], errors_for=keys)

    result = _importer(xray).find_issues(keys)

    assert result == IssueLookupResult(found={}, missing=frozenset())
    assert len(xray.queries) == 10 + 2 * 50


@pytest.mark.parametrize(
    "raw",
    [
        {"data": {"getTests": {"total": 1, "results": "nope"}}},
        {"data": {"getTests": {"results": []}}},
        {"data": {"getTests": {"total": 1, "results": [{"jira": {"key": "QA-1"}}]}}},
        {"data": None},
    ],
)
def test_malformed_search_answers_raise(raw: dict[str, object]) -> None:
    xray = _Search()
    xray.raw = raw

    with pytest.raises(ConnectorError):
        _importer(xray).find_issues(["QA-1"])


@pytest.mark.parametrize("code", [401, 403])
def test_unauthorized_search_raises_auth_error(code: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/authenticate":
            return httpx.Response(200, json=TOKEN)
        return httpx.Response(code, text=f"vendor body {CLIENT_SECRET}")

    with pytest.raises(ConnectorAuthError) as caught:
        _importer(handler).find_issues(["QA-1"])

    _assert_secret_free(caught.value)


def test_invalid_keys_are_never_put_into_jql() -> None:
    xray = _Search()

    result = _importer(xray).find_issues(['QA-1") OR key in ("X-1'])

    assert xray.queries == []
    assert result.found == {}


def test_linked_tests_pages_through_tests_linked_to_the_story() -> None:
    xray = _Search(
        tests=[_jira("QA-5", "Login", "1", "Test"), _jira("QA-6", "Logout", "1", "Test")], page=1
    )

    linked = _importer(xray).linked_tests("ABC-1")

    assert [t.key for t in linked] == ["QA-5", "QA-6"]
    assert all(t.is_test for t in linked)
    assert xray.queries[0]["variables"]["jql"] == 'issue in linkedIssues("ABC-1")'


def test_linked_tests_fails_closed_on_graphql_errors() -> None:
    xray = _Search(errors_for=["ABC-1"])

    with pytest.raises(ConnectorError):
        _importer(xray).linked_tests("ABC-1")
