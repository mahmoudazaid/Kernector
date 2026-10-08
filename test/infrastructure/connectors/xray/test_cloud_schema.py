"""Xray Cloud schema discovery through httpx.MockTransport; no live Xray."""

from __future__ import annotations

import json

import httpx
import pytest

from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorNetworkError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    ConnectorUnavailableError,
)
from domain.test_management.xray import XrayTestCreateSchema
from infrastructure.connectors.xray.cloud import XrayCloudImporter
from infrastructure.connectors.xray.errors import XraySchemaError
from infrastructure.connectors.xray.schema import XraySchemaCache

BASE_URL = "https://xray.example.test"
CLIENT_ID = "cloud-client-id"
CLIENT_SECRET = "cloud-client-secret-XYZ"
TOKEN = "xray-bearer-token-ABC"

_TEST_TYPES = [
    {"id": "t-manual", "name": "Manual", "kind": "Steps"},
    {"id": "t-cucumber", "name": "Cucumber", "kind": "Gherkin"},
    {"id": "t-generic", "name": "Generic", "kind": "Unstructured"},
]


def _settings_response(test_types: list[dict[str, str]] | None) -> httpx.Response:
    settings = None if test_types is None else {"testTypeSettings": {"testTypes": test_types}}
    return httpx.Response(200, json={"data": {"getProjectSettings": settings}})


class _Xray:
    def __init__(self, test_types: list[dict[str, str]] | None = _TEST_TYPES) -> None:
        self.test_types = test_types
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/v2/authenticate":
            return httpx.Response(200, json=TOKEN)
        return _settings_response(self.test_types)

    def graphql_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == "/api/v2/graphql"]


def _importer(
    handler, *, cache: XraySchemaCache | None = None, link_type: str = "Test"
) -> XrayCloudImporter:
    return XrayCloudImporter(
        base_url=BASE_URL,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        project_key="QA",
        link_type=link_type,
        cache=cache or XraySchemaCache(),
        transport=httpx.MockTransport(handler),
    )


def test_schema_discovers_test_types_by_kind_after_authenticating() -> None:
    xray = _Xray()

    schema = _importer(xray).schema()

    assert schema == XrayTestCreateSchema(
        project_key="QA",
        supports_manual=True,
        supports_cucumber=True,
        supports_issue_link=True,
    )
    auth, query = xray.requests
    assert auth.method == "POST"
    assert str(auth.url) == f"{BASE_URL}/api/v2/authenticate"
    assert json.loads(auth.content) == {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    assert str(query.url) == f"{BASE_URL}/api/v2/graphql"
    assert query.headers["Authorization"] == f"Bearer {TOKEN}"
    body = json.loads(query.content)
    assert "getProjectSettings" in body["query"]
    assert body["variables"] == {"projectKey": "QA"}


def test_schema_reports_missing_kinds_and_blank_link_type_as_unsupported() -> None:
    xray = _Xray(test_types=[{"id": "t-generic", "name": "Generic", "kind": "Unstructured"}])

    schema = _importer(xray, link_type=" ").schema()

    assert schema == XrayTestCreateSchema(
        project_key="QA",
        supports_manual=False,
        supports_cucumber=False,
        supports_issue_link=False,
    )


def test_schema_without_project_settings_raises_schema_error() -> None:
    with pytest.raises(XraySchemaError):
        _importer(_Xray(test_types=None)).schema()


def test_schema_is_reused_from_the_shared_cache_without_metadata_calls() -> None:
    cache = XraySchemaCache()
    first, second = _Xray(), _Xray()

    _importer(first, cache=cache).schema()
    schema = _importer(second, cache=cache).schema()

    assert schema.supports_manual is True
    assert second.requests == []


def test_cache_entries_are_scoped_by_project() -> None:
    cache = XraySchemaCache()
    _importer(_Xray(), cache=cache).schema()
    other = _Xray(test_types=[])

    schema = XrayCloudImporter(
        base_url=BASE_URL,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        project_key="OPS",
        link_type="Test",
        cache=cache,
        transport=httpx.MockTransport(other),
    ).schema()

    assert schema.supports_manual is False
    assert len(other.graphql_requests()) == 1


def test_invalidated_cache_entry_is_rediscovered() -> None:
    cache = XraySchemaCache()
    _importer(_Xray(), cache=cache).schema()
    cache.invalidate(("cloud", BASE_URL, "QA"))
    xray = _Xray(test_types=[])

    schema = _importer(xray, cache=cache).schema()

    assert schema.supports_manual is False
    assert len(xray.graphql_requests()) == 1


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ConnectorAuthError),
        (403, ConnectorAuthError),
        (429, ConnectorRateLimitError),
        (503, ConnectorUnavailableError),
    ],
)
def test_authentication_failures_are_typed_and_secret_free(status: int, expected) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=f"vendor detail {CLIENT_SECRET}")

    with pytest.raises(expected) as caught:
        _importer(handler).schema()

    _assert_secret_free(caught.value)


def test_graphql_errors_are_secret_free_request_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/authenticate":
            return httpx.Response(200, json=TOKEN)
        return httpx.Response(
            200, json={"errors": [{"message": f"customfield_10200 broke {TOKEN}"}], "data": None}
        )

    with pytest.raises(ConnectorError) as caught:
        _importer(handler).schema()

    _assert_secret_free(caught.value)


def test_timeouts_and_network_failures_are_unavailable() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    def network(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(ConnectorTimeoutError):
        _importer(timeout).schema()
    with pytest.raises(ConnectorNetworkError):
        _importer(network).schema()


def test_repr_masks_the_client_secret() -> None:
    assert CLIENT_SECRET not in repr(_importer(_Xray()))


def _assert_secret_free(error: BaseException) -> None:
    chain = [error, error.__cause__, error.__context__]
    rendered = " ".join(str(e) for e in chain if e is not None)
    for secret in (CLIENT_SECRET, TOKEN, "vendor detail", "customfield"):
        assert secret not in rendered
