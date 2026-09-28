"""Jira Cloud REST client boundary (OAuth 2.0 3LO, ``api.atlassian.com``)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorNetworkError,
    ConnectorNotFoundError,
    ConnectorTimeoutError,
    ConnectorUnavailableError,
)
from infrastructure.connectors.jira.errors import JiraPaginationError, JiraRateLimitError

_MSG_AUTH = "Jira rejected the connector credentials or permissions."
_MSG_NOT_FOUND = "The Jira resource was not found."
_MSG_TIMEOUT = "The Jira request timed out."
_MSG_NETWORK = "The Jira network request failed."
_MSG_UNAVAILABLE = "Jira is temporarily unavailable."
_MSG_REQUEST_FAILED = "The Jira request failed."
_API_BASE = "https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"


@dataclass(frozen=True, slots=True)
class JiraIssuePage:
    """One page of ``POST /rest/api/3/search/jql`` results."""

    issues: Sequence[Mapping[str, object]]
    next_page_token: str | None
    is_last: bool


@dataclass(frozen=True, slots=True)
class JiraProject:
    """A Jira project visible to the authorized user."""

    key: str
    name: str


@dataclass(frozen=True, slots=True)
class JiraProjectPage:
    """One page of ``GET /rest/api/3/project/search`` for the Hub picker."""

    items: tuple[JiraProject, ...]
    is_last: bool
    next_start_at: int | None


class JiraClient(Protocol):
    """Read-only Jira Cloud operations used by the connector and picker."""

    def search_issues(
        self,
        jql: str,
        fields: Sequence[str],
        page_size: int,
        next_page_token: str | None,
    ) -> JiraIssuePage: ...

    def list_projects(self, *, start_at: int, max_results: int) -> JiraProjectPage: ...

    def get_project(self, key: str) -> JiraProject: ...


class HttpJiraClient:
    """httpx implementation of :class:`JiraClient` for one Jira Cloud site."""

    def __init__(
        self,
        access_token: str,
        cloud_id: str,
        *,
        timeout: float = 30.0,
        transport: object | None = None,
    ) -> None:
        import httpx

        self._httpx = httpx
        self._client = httpx.Client(
            base_url=_API_BASE.format(cloud_id=cloud_id),
            timeout=timeout,
            transport=transport,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "kernector-jira-connector",
            },
        )

    def __repr__(self) -> str:
        return "HttpJiraClient(access_token='***')"

    def search_issues(
        self,
        jql: str,
        fields: Sequence[str],
        page_size: int,
        next_page_token: str | None,
    ) -> JiraIssuePage:
        body: dict[str, object] = {
            "jql": jql,
            "fields": list(fields),
            "maxResults": page_size,
        }
        if next_page_token is not None:
            body["nextPageToken"] = next_page_token
        payload = self._request_json("POST", "/search/jql", json=body)
        issues = payload.get("issues")
        if not isinstance(issues, list):
            raise JiraPaginationError()
        token = payload.get("nextPageToken")
        return JiraIssuePage(
            issues=issues,
            next_page_token=token if isinstance(token, str) and token else None,
            is_last=payload.get("isLast") is True,
        )

    def list_projects(self, *, start_at: int, max_results: int) -> JiraProjectPage:
        payload = self._request_json(
            "GET",
            "/project/search",
            params={"startAt": start_at, "maxResults": max_results, "orderBy": "key"},
        )
        values = payload.get("values")
        if not isinstance(values, list) or payload.get("startAt") != start_at:
            raise JiraPaginationError()
        items = tuple(_project(value) for value in values)
        is_last = payload.get("isLast") is True
        if is_last:
            return JiraProjectPage(items=items, is_last=True, next_start_at=None)
        if not items:
            raise JiraPaginationError()
        return JiraProjectPage(
            items=items, is_last=False, next_start_at=start_at + len(items)
        )

    def get_project(self, key: str) -> JiraProject:
        return _project(self._request_json("GET", f"/project/{quote(key, safe='')}"))

    def _request_json(
        self,
        method: str,
        path: str,
        **kwargs: object,
    ) -> Mapping[str, object]:
        try:
            response = self._client.request(method, path, **kwargs)
            response.raise_for_status()
            payload = response.json()
        except Exception as error:
            raise _map_httpx_error(error, self._httpx) from None
        if not isinstance(payload, Mapping):
            raise ConnectorError(_MSG_REQUEST_FAILED)
        return payload


def _project(raw: object) -> JiraProject:
    if not isinstance(raw, Mapping):
        raise ConnectorError(_MSG_REQUEST_FAILED)
    key = raw.get("key")
    name = raw.get("name")
    if not isinstance(key, str) or not key or not isinstance(name, str):
        raise ConnectorError(_MSG_REQUEST_FAILED)
    return JiraProject(key=key, name=name)


def _retry_after(raw: str | None) -> int | None:
    if raw is None or not raw.strip().isdigit():
        return None
    return int(raw.strip())


def _map_httpx_error(error: BaseException, httpx_module: object) -> ConnectorError:
    http_status_error = getattr(httpx_module, "HTTPStatusError")
    request_error = getattr(httpx_module, "RequestError")
    timeout_error = getattr(httpx_module, "TimeoutException")
    if isinstance(error, http_status_error):
        status = int(error.response.status_code)
        if status in {401, 403}:
            return ConnectorAuthError(_MSG_AUTH)
        if status == 404:
            return ConnectorNotFoundError(_MSG_NOT_FOUND)
        if status == 429:
            return JiraRateLimitError(_retry_after(error.response.headers.get("Retry-After")))
        if status >= 500:
            return ConnectorUnavailableError(_MSG_UNAVAILABLE)
        return ConnectorError(_MSG_REQUEST_FAILED)
    if isinstance(error, timeout_error):
        return ConnectorTimeoutError(_MSG_TIMEOUT)
    if isinstance(error, request_error):
        return ConnectorNetworkError(_MSG_NETWORK)
    if isinstance(error, ConnectorError):
        return error
    return ConnectorError(_MSG_REQUEST_FAILED)
