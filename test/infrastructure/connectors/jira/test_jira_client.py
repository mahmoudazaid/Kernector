"""HttpJiraClient tests through httpx.MockTransport; no live Jira."""

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
from infrastructure.connectors.jira.client import HttpJiraClient, JiraProject
from infrastructure.connectors.jira.errors import JiraPaginationError, JiraRateLimitError

SECRET = "atlassian-access-secret-123"
CLOUD_ID = "11223344-a1b2-3b33-c444-def123456789"
BASE = f"https://api.atlassian.com/ex/jira/{CLOUD_ID}/rest/api/3"


def _client(handler) -> HttpJiraClient:
    return HttpJiraClient(SECRET, CLOUD_ID, transport=httpx.MockTransport(handler))


def test_search_issues_posts_enhanced_jql_search_and_parses_page() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "issues": [{"key": "KAN-1", "fields": {"summary": "One"}}],
                "nextPageToken": "tok-2",
                "isLast": False,
            },
        )

    page = _client(handler).search_issues(
        'project = "KAN" ORDER BY key ASC', ("summary", "updated"), 50, "tok-1"
    )

    [request] = seen
    assert request.method == "POST"
    assert str(request.url) == f"{BASE}/search/jql"
    assert request.headers["Authorization"] == f"Bearer {SECRET}"
    assert json.loads(request.content) == {
        "jql": 'project = "KAN" ORDER BY key ASC',
        "fields": ["summary", "updated"],
        "maxResults": 50,
        "nextPageToken": "tok-1",
    }
    assert page.issues == [{"key": "KAN-1", "fields": {"summary": "One"}}]
    assert page.next_page_token == "tok-2"
    assert page.is_last is False


def test_search_issues_first_page_omits_token_and_last_page_has_no_token() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"issues": [], "isLast": True})

    page = _client(handler).search_issues("project = X", ("summary",), 10, None)

    assert "nextPageToken" not in bodies[0]
    assert page.is_last is True
    assert page.next_page_token is None


def test_search_issues_with_non_list_issues_raises_pagination_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"issues": {"oops": 1}, "isLast": True})

    with pytest.raises(JiraPaginationError):
        _client(handler).search_issues("project = X", ("summary",), 10, None)


def test_list_projects_reads_one_paginated_page() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "startAt": 50,
                "maxResults": 2,
                "isLast": False,
                "values": [
                    {"key": "KAN", "name": "Kanban"},
                    {"key": "OPS", "name": "Operations"},
                ],
            },
        )

    page = _client(handler).list_projects(start_at=50, max_results=2)

    [request] = seen
    assert request.method == "GET"
    assert request.url.path == f"/ex/jira/{CLOUD_ID}/rest/api/3/project/search"
    assert dict(request.url.params) == {"startAt": "50", "maxResults": "2", "orderBy": "key"}
    assert page.items == (JiraProject("KAN", "Kanban"), JiraProject("OPS", "Operations"))
    assert page.is_last is False
    assert page.next_start_at == 52


def test_list_projects_last_page_has_no_next_start() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"startAt": 0, "isLast": True, "values": [{"key": "KAN", "name": "K"}]}
        )

    page = _client(handler).list_projects(start_at=0, max_results=50)

    assert page.is_last is True
    assert page.next_start_at is None


@pytest.mark.parametrize(
    "payload",
    [
        {"startAt": 0, "isLast": False, "values": []},
        {"startAt": 10, "isLast": False, "values": [{"key": "KAN", "name": "K"}]},
        {"startAt": 0, "isLast": False, "values": "nope"},
    ],
)
def test_list_projects_non_advancing_page_raises(payload: dict[str, object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(JiraPaginationError):
        _client(handler).list_projects(start_at=0, max_results=50)


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
def test_http_status_maps_to_typed_connector_error(status: int, expected: type) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=f"upstream said {SECRET}")

    with pytest.raises(expected) as caught:
        _client(handler).search_issues("project = X", ("summary",), 10, None)

    assert type(caught.value) is expected or issubclass(type(caught.value), expected)
    assert SECRET not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_rate_limit_exposes_retry_after_without_retrying() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "17"})

    with pytest.raises(JiraRateLimitError) as caught:
        _client(handler).search_issues("project = X", ("summary",), 10, None)

    assert caught.value.retry_after_seconds == 17
    assert calls == 1


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

    with pytest.raises(expected):
        _client(handler).search_issues("project = X", ("summary",), 10, None)


def test_client_repr_never_contains_token() -> None:
    client = _client(lambda request: httpx.Response(200, json={}))

    assert SECRET not in repr(client)


def test_get_project_reads_one_project_and_maps_missing_to_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/project/KAN"):
            return httpx.Response(200, json={"key": "KAN", "name": "Kanban"})
        return httpx.Response(404, json={"errorMessages": ["No project"]})

    client = _client(handler)

    assert client.get_project("KAN") == JiraProject("KAN", "Kanban")
    with pytest.raises(ConnectorNotFoundError):
        client.get_project("NOPE")
