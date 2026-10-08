"""XrayCloudImporter create behaviour through httpx.MockTransport; no live Xray."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from domain.errors import ConnectorAuthError, ConnectorError, ConnectorUnavailableError
from domain.test_management.xray import XrayImportResult, XrayTestSpec, XrayTestStep
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
