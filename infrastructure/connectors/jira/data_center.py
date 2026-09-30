"""Jira Data Center / Server REST client (``/rest/api/2``, Personal Access Token).

The PAT is sent only to the configured base URL: redirects are never followed.
Raw upstream failures stay on ``__cause__`` as a token-free diagnostic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, TypeGuard
from urllib.parse import quote, urlsplit

from domain.errors import ConnectorError
from infrastructure.connectors.jira.client import (
    JiraIssuePage,
    JiraProject,
    JiraProjectPage,
    map_httpx_error,
    parse_project,
)
from infrastructure.connectors.jira.errors import JiraPaginationError
from infrastructure.connectors.jira.site import JiraSite

if TYPE_CHECKING:
    import httpx

_MSG_REQUEST_FAILED = "The Jira request failed."
_DIAGNOSTIC_BODY_LIMIT = 500
_REDACTED = "***"


class JiraDataCenterHttpDiagnostic(RuntimeError):
    """Token-free record of the raw upstream failure, kept on ``__cause__``.

    It replaces the httpx exception so the request (and its Authorization
    header) is not reachable from the raised error.
    """


class HttpJiraDataCenterClient:
    """httpx implementation of :class:`JiraClient` for one Data Center instance.

    The ``next_page_token`` is the next ``startAt`` offset as a decimal string.
    Each response is validated on its own; cross-page invariants such as a stable
    ``total`` belong to the pagination consumer.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        import httpx

        self._httpx = httpx
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=f"{self._base_url}/rest/api/2",
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "kernector-jira-connector",
            },
        )

    def __repr__(self) -> str:
        return f"HttpJiraDataCenterClient(base_url={self._base_url!r}, token='***')"

    def search_issues(
        self,
        jql: str,
        fields: Sequence[str],
        page_size: int,
        next_page_token: str | None,
    ) -> JiraIssuePage:
        start_at = _start_at(next_page_token)
        payload = self._request_json(
            "POST",
            "/search",
            json={
                "jql": jql,
                "startAt": start_at,
                "maxResults": page_size,
                "fields": list(fields),
            },
        )
        issues = payload.get("issues")
        total = payload.get("total")
        if (
            not isinstance(issues, list)
            or not _is_int(payload.get("startAt"))
            or payload.get("startAt") != start_at
            or not _is_int(total)
            or total < 0
        ):
            raise JiraPaginationError()
        if not issues and start_at < total:
            raise JiraPaginationError()
        next_start = start_at + len(issues)
        is_last = next_start >= total
        return JiraIssuePage(
            issues=issues,
            next_page_token=None if is_last else str(next_start),
            is_last=is_last,
            total=total,
        )

    def list_projects(self, *, start_at: int, max_results: int) -> JiraProjectPage:
        payload = self._request("GET", "/project")
        if not isinstance(payload, list):
            raise ConnectorError(_MSG_REQUEST_FAILED)
        projects = tuple(parse_project(value) for value in payload)
        end = start_at + max_results
        items = projects[start_at:end]
        if end >= len(projects):
            return JiraProjectPage(items=items, is_last=True, next_start_at=None)
        return JiraProjectPage(items=items, is_last=False, next_start_at=end)

    def get_project(self, key: str) -> JiraProject:
        return parse_project(self._request_json("GET", f"/project/{quote(key, safe='')}"))

    def get_issue(self, key: str, fields: Sequence[str]) -> Mapping[str, object]:
        """Read one issue, requesting only ``fields`` to keep the payload bounded."""
        return self._request_json(
            "GET",
            f"/issue/{quote(key, safe='')}",
            params={"fields": ",".join(fields)},
        )

    def server_info(self) -> JiraSite:
        """Identify the instance: ``serverId``, else a stable hash of the base URL."""
        payload = self._request_json("GET", "/serverInfo")
        server_id = payload.get("serverId")
        title = payload.get("serverTitle")
        instance_id = (
            server_id.strip()
            if isinstance(server_id, str) and server_id.strip()
            else _url_instance_id(self._base_url)
        )
        name = (
            title.strip()
            if isinstance(title, str) and title.strip()
            else urlsplit(self._base_url).hostname or self._base_url
        )
        return JiraSite(cloud_id=instance_id, site_url=self._base_url, name=name)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: object = None,
        params: Mapping[str, str] | None = None,
    ) -> Mapping[str, object]:
        payload = self._request(method, path, json=json, params=params)
        if not isinstance(payload, Mapping):
            raise ConnectorError(_MSG_REQUEST_FAILED)
        return payload

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: object = None,
        params: Mapping[str, str] | None = None,
    ) -> object:
        try:
            response = self._client.request(method, path, json=json, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as error:
            mapped = map_httpx_error(error, self._httpx)
            diagnostic = self._diagnostic(error)
        # Raised outside the handler so the httpx error is not kept as __context__.
        raise mapped from diagnostic

    def _diagnostic(self, error: BaseException) -> JiraDataCenterHttpDiagnostic:
        response = getattr(error, "response", None)
        if isinstance(error, self._httpx.HTTPStatusError) and response is not None:
            detail = f"HTTP {response.status_code}: {response.text[:_DIAGNOSTIC_BODY_LIMIT]}"
        else:
            detail = f"{type(error).__name__}: {error}"
        return JiraDataCenterHttpDiagnostic(detail.replace(self._token, _REDACTED))


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _url_instance_id(base_url: str) -> str:
    parts = urlsplit(base_url)
    normalized = f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip('/')}"
    return "url-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _start_at(token: str | None) -> int:
    if token is None:
        return 0
    if not (token.isascii() and token.isdigit()):
        raise JiraPaginationError()
    return int(token)
