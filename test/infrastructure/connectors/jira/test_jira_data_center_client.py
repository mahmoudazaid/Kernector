"""HttpJiraDataCenterClient tests through httpx.MockTransport; no live Jira."""

from __future__ import annotations

import json

import httpx
import pytest

from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorNetworkError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    ConnectorUnavailableError,
)
from infrastructure.connectors.jira.client import JiraProject
from infrastructure.connectors.jira.data_center import HttpJiraDataCenterClient
from infrastructure.connectors.jira.errors import JiraPaginationError
from infrastructure.connectors.jira.site import JiraSite

TOKEN = "dc-personal-access-token-XYZ"
BASE_URL = "https://jira.example.com/jira"
API = f"{BASE_URL}/rest/api/2"
JQL = 'project = "KAN" ORDER BY key ASC'


def _client(handler) -> HttpJiraDataCenterClient:
    return HttpJiraDataCenterClient(
        BASE_URL, TOKEN, transport=httpx.MockTransport(handler)
    )


def _search_payload(start_at: int, total: int, keys: list[str]) -> dict[str, object]:
    return {
        "startAt": start_at,
        "maxResults": 2,
        "total": total,
        "issues": [{"key": key, "fields": {"summary": key}} for key in keys],
    }


def test_search_posts_rest_api_2_search_with_bearer_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_search_payload(0, 3, ["KAN-1", "KAN-2"]))

    page = _client(handler).search_issues(JQL, ("summary", "updated"), 2, None)

    [request] = seen
    assert request.method == "POST"
    assert str(request.url) == f"{API}/search"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {
        "jql": JQL,
        "startAt": 0,
        "maxResults": 2,
        "fields": ["summary", "updated"],
    }
    assert [issue["key"] for issue in page.issues] == ["KAN-1", "KAN-2"]
    assert page.next_page_token == "2"
    assert page.is_last is False
    assert page.total == 3


def test_search_resumes_from_the_start_at_token_and_detects_the_last_page() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_search_payload(2, 3, ["KAN-3"]))

    page = _client(handler).search_issues(JQL, ("summary",), 2, "2")

    assert bodies[0]["startAt"] == 2
    assert page.is_last is True
    assert page.next_page_token is None
    assert page.total == 3


def test_empty_project_is_a_last_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_search_payload(0, 0, []))

    page = _client(handler).search_issues(JQL, ("summary",), 2, None)

    assert page.issues == []
    assert page.is_last is True


@pytest.mark.parametrize(
    "payload",
    [
        _search_payload(5, 10, ["KAN-6"]),
        {**_search_payload(0, 10, ["KAN-1"]), "total": -1},
        {**_search_payload(0, 10, ["KAN-1"]), "total": "10"},
        {**_search_payload(0, 10, ["KAN-1"]), "startAt": True},
        _search_payload(0, 10, []),
        {**_search_payload(0, 10, []), "issues": {"KAN-1": {}}},
    ],
    ids=[
        "echoed-start-mismatch",
        "negative-total",
        "non-integer-total",
        "boolean-start",
        "empty-page-before-total",
        "issues-not-a-list",
    ],
)
def test_inconsistent_search_page_raises_pagination_error(
    payload: dict[str, object],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(JiraPaginationError):
        _client(handler).search_issues(JQL, ("summary",), 2, None)


@pytest.mark.parametrize("token", ["abc", "-2", " ", "2.5", "\u00b2"])
def test_non_numeric_start_token_is_rejected_before_any_request(token: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_search_payload(0, 0, []))

    with pytest.raises(JiraPaginationError):
        _client(handler).search_issues(JQL, ("summary",), 2, token)

    assert calls == 0


def _projects_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/jira/rest/api/2/project":
        return httpx.Response(
            200,
            json=[
                {"key": "KAN", "name": "Kanban"},
                {"key": "OPS", "name": "Operations"},
                {"key": "WEB", "name": "Website"},
            ],
        )
    if request.url.path == "/jira/rest/api/2/project/KAN":
        return httpx.Response(200, json={"key": "KAN", "name": "Kanban"})
    return httpx.Response(404, json={"errorMessages": ["No project"]})


def test_list_projects_slices_the_full_project_list_into_pages() -> None:
    client = _client(_projects_handler)

    first = client.list_projects(start_at=0, max_results=2)
    second = client.list_projects(start_at=2, max_results=2)

    assert first.items == (JiraProject("KAN", "Kanban"), JiraProject("OPS", "Operations"))
    assert first.is_last is False
    assert first.next_start_at == 2
    assert second.items == (JiraProject("WEB", "Website"),)
    assert second.is_last is True
    assert second.next_start_at is None


def test_list_projects_rejects_a_non_list_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"values": []})

    with pytest.raises(ConnectorError):
        _client(handler).list_projects(start_at=0, max_results=10)


def test_get_project_reads_one_project_and_maps_missing_to_not_found() -> None:
    client = _client(_projects_handler)

    assert client.get_project("KAN") == JiraProject("KAN", "Kanban")
    with pytest.raises(ConnectorNotFoundError):
        client.get_project("NOPE")


def test_server_info_identifies_the_instance_by_server_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/jira/rest/api/2/serverInfo"
        return httpx.Response(
            200,
            json={
                "baseUrl": "http://internal-host:8080/jira",
                "serverTitle": "Example Jira",
                "serverId": "B8E7-4C2A-9F31-0D6E",
                "version": "9.12.4",
            },
        )

    site = _client(handler).server_info()

    assert site == JiraSite(
        cloud_id="B8E7-4C2A-9F31-0D6E", site_url=BASE_URL, name="Example Jira"
    )


def test_server_info_without_server_id_falls_back_to_a_stable_url_hash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"version": "9.12.4"})

    first = _client(handler).server_info()
    again = HttpJiraDataCenterClient(
        BASE_URL + "/", TOKEN, transport=httpx.MockTransport(handler)
    ).server_info()
    other = HttpJiraDataCenterClient(
        "https://other.example.com", TOKEN, transport=httpx.MockTransport(handler)
    ).server_info()

    assert first.instance_id.startswith("url-")
    assert len(first.instance_id) == len("url-") + 16
    assert again.instance_id == first.instance_id
    assert other.instance_id != first.instance_id
    assert first.name == "jira.example.com"
    assert first.site_url == BASE_URL


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ConnectorAuthError),
        (403, ConnectorAuthError),
        (404, ConnectorNotFoundError),
        (429, ConnectorRateLimitError),
        (500, ConnectorUnavailableError),
        (503, ConnectorUnavailableError),
        (400, ConnectorError),
    ],
)
def test_http_status_maps_to_typed_errors_with_a_token_free_cause(
    status: int, expected: type
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=f"upstream echoed Bearer {TOKEN}")

    with pytest.raises(expected) as caught:
        _client(handler).search_issues(JQL, ("summary",), 2, None)

    chain = _chain(caught.value)
    assert len(chain) == 2
    assert f"HTTP {status}" in str(chain[1])
    assert "upstream echoed Bearer ***" in str(chain[1])
    for error in chain:
        assert TOKEN not in str(error)
        assert TOKEN not in repr(error)
    assert caught.value.__context__ is None


def test_redirects_are_not_followed_so_the_token_never_leaves_the_instance() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://sso.example.net/login"})

    with pytest.raises(ConnectorError):
        _client(handler).search_issues(JQL, ("summary",), 2, None)

    assert [str(request.url) for request in seen] == [f"{API}/search"]


def test_non_json_login_page_is_a_request_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>Log in</html>")

    with pytest.raises(ConnectorError) as caught:
        _client(handler).server_info()

    assert not isinstance(caught.value, ConnectorUnavailableError)


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (httpx.ReadTimeout("slow"), ConnectorTimeoutError),
        (httpx.ConnectError("down"), ConnectorNetworkError),
    ],
)
def test_transport_failures_map_to_retryable_errors(
    raised: Exception, expected: type
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise raised

    with pytest.raises(expected) as caught:
        _client(handler).search_issues(JQL, ("summary",), 2, None)

    for error in _chain(caught.value):
        assert TOKEN not in str(error)
        assert TOKEN not in repr(error)


def test_client_repr_never_contains_token() -> None:
    client = _client(lambda request: httpx.Response(200, json={}))

    assert TOKEN not in repr(client)
    assert BASE_URL in repr(client)


def _chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain
