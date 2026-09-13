"""GitHub API client boundary for knowledge connectors."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from typing import Protocol

from domain.errors import ConnectorAuthError, ConnectorError, ConnectorUnavailableError

_MSG_AUTH = "GitHub rejected the connector credentials or permissions."
_MSG_UNAVAILABLE = "GitHub is temporarily unavailable."
_MSG_REQUEST_FAILED = "The GitHub request failed."
_MSG_INCOMPLETE_TREE = "GitHub returned an incomplete repository listing."
_MSG_CONFIG = "GitHub connector optional dependency is missing; install kernector[github]."


class GitHubConfigError(RuntimeError):
    """GitHub connector settings or optional dependencies are unusable."""


class GitHubClient(Protocol):
    """Narrow GitHub operations required by repository and issue adapters."""

    def resolve_commit_sha(self, owner: str, repo: str, ref: str) -> str:
        """Resolve a branch, tag, or SHA-ish ref to a commit SHA."""
        ...

    def get_git_tree(
        self,
        owner: str,
        repo: str,
        tree_sha: str,
        *,
        recursive: bool = True,
    ) -> Mapping[str, object]:
        """Return a Git tree payload."""
        ...

    def get_blob_content(self, owner: str, repo: str, blob_sha: str) -> bytes:
        """Return decoded blob bytes."""
        ...

    def get_project_v2_items(self, project_node_id: str) -> Sequence[Mapping[str, object]]:
        """Return all ProjectV2 item content nodes, walking all pages."""
        ...

    def resolve_project_v2_id(self, owner_login: str, number: int) -> str:
        """Resolve a user/org ProjectV2 number to its node id."""
        ...


class HttpGitHubClient:
    """HTTP implementation of the GitHub client protocol."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.github.com",
        timeout: float = 30.0,
        page_size: int = 100,
        transport: object | None = None,
    ) -> None:
        try:
            import httpx
        except ImportError as error:  # pragma: no cover - exercised without extra.
            raise GitHubConfigError(_MSG_CONFIG) from error
        self._httpx = httpx
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "kernector-github-connector",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        self._page_size = page_size

    def resolve_commit_sha(self, owner: str, repo: str, ref: str) -> str:
        payload = self._get_json(f"/repos/{owner}/{repo}/commits/{ref}")
        sha = payload.get("sha")
        if not isinstance(sha, str) or not sha.strip():
            raise ConnectorError(_MSG_REQUEST_FAILED)
        return sha

    def get_git_tree(
        self,
        owner: str,
        repo: str,
        tree_sha: str,
        *,
        recursive: bool = True,
    ) -> Mapping[str, object]:
        params = {"recursive": "1"} if recursive else None
        payload = self._get_json(f"/repos/{owner}/{repo}/git/trees/{tree_sha}", params=params)
        if payload.get("truncated") is True:
            raise ConnectorUnavailableError(_MSG_INCOMPLETE_TREE)
        tree = payload.get("tree")
        if not isinstance(tree, Sequence) or isinstance(tree, (str, bytes)):
            raise ConnectorError(_MSG_REQUEST_FAILED)
        return payload

    def get_blob_content(self, owner: str, repo: str, blob_sha: str) -> bytes:
        payload = self._get_json(f"/repos/{owner}/{repo}/git/blobs/{blob_sha}")
        content = payload.get("content")
        encoding = payload.get("encoding")
        if not isinstance(content, str) or encoding != "base64":
            raise ConnectorError(_MSG_REQUEST_FAILED)
        try:
            return base64.b64decode(content, validate=False)
        except ValueError as error:
            raise ConnectorError(_MSG_REQUEST_FAILED) from error

    def get_project_v2_items(self, project_node_id: str) -> Sequence[Mapping[str, object]]:
        items: list[Mapping[str, object]] = []
        after: str | None = None
        while True:
            payload = self._graphql(_PROJECT_V2_ITEMS_QUERY, {"projectId": project_node_id, "after": after, "first": self._page_size})
            project = _nested_mapping(payload, ("data", "node"))
            if project.get("__typename") != "ProjectV2":
                raise ConnectorError(_MSG_REQUEST_FAILED)
            page = project.get("items")
            if not isinstance(page, Mapping):
                raise ConnectorError(_MSG_REQUEST_FAILED)
            nodes = page.get("nodes")
            if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
                raise ConnectorError(_MSG_REQUEST_FAILED)
            for node in nodes:
                if isinstance(node, Mapping):
                    content = node.get("content")
                    if isinstance(content, Mapping):
                        items.append(content)
            page_info = page.get("pageInfo")
            if not isinstance(page_info, Mapping):
                raise ConnectorError(_MSG_REQUEST_FAILED)
            has_next = page_info.get("hasNextPage")
            end_cursor = page_info.get("endCursor")
            if has_next is False:
                return tuple(items)
            if has_next is not True or not isinstance(end_cursor, str) or not end_cursor:
                raise ConnectorError(_MSG_REQUEST_FAILED)
            after = end_cursor

    def resolve_project_v2_id(self, owner_login: str, number: int) -> str:
        # Query org and user separately: a login is only one of them, and a
        # combined document always carries a top-level NOT_FOUND/FORBIDDEN
        # error for the other root even when the project id is present.
        for query, root in (
            (_PROJECT_V2_ORG_LOOKUP_QUERY, "organization"),
            (_PROJECT_V2_USER_LOOKUP_QUERY, "user"),
        ):
            payload = self._graphql(
                query,
                {"login": owner_login, "number": number},
                soft_lookup_miss=True,
            )
            owner = _optional_nested_mapping(payload, ("data", root))
            if owner is None:
                continue
            project = owner.get("projectV2")
            if isinstance(project, Mapping):
                project_id = project.get("id")
                if isinstance(project_id, str) and project_id.strip():
                    return project_id
        raise ConnectorError(_MSG_REQUEST_FAILED)

    def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception as error:
            raise _map_httpx_error(error, self._httpx) from error
        if not isinstance(payload, Mapping):
            raise ConnectorError(_MSG_REQUEST_FAILED)
        return payload

    def _graphql(
        self,
        query: str,
        variables: Mapping[str, object],
        *,
        soft_lookup_miss: bool = False,
    ) -> Mapping[str, object]:
        try:
            response = self._client.post("/graphql", json={"query": query, "variables": dict(variables)})
            response.raise_for_status()
            payload = response.json()
        except Exception as error:
            raise _map_httpx_error(error, self._httpx) from error
        if not isinstance(payload, Mapping):
            raise ConnectorError(_MSG_REQUEST_FAILED)
        errors = payload.get("errors")
        if errors:
            if soft_lookup_miss and _is_soft_lookup_miss(errors):
                return payload
            raise ConnectorError(_MSG_REQUEST_FAILED)
        return payload


def _nested_mapping(payload: Mapping[str, object], keys: Sequence[str]) -> Mapping[str, object]:
    current: object = payload
    for key in keys:
        if not isinstance(current, Mapping):
            raise ConnectorError(_MSG_REQUEST_FAILED)
        current = current.get(key)
    if not isinstance(current, Mapping):
        raise ConnectorError(_MSG_REQUEST_FAILED)
    return current


def _optional_nested_mapping(
    payload: Mapping[str, object], keys: Sequence[str]
) -> Mapping[str, object] | None:
    current: object = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    if not isinstance(current, Mapping):
        return None
    return current


def _map_httpx_error(error: BaseException, httpx_module: object) -> ConnectorError:
    http_status_error = getattr(httpx_module, "HTTPStatusError")
    request_error = getattr(httpx_module, "RequestError")
    if isinstance(error, http_status_error):
        status = int(error.response.status_code)
        if status in {401, 403}:
            return ConnectorAuthError(_MSG_AUTH)
        if status == 429 or status >= 500:
            return ConnectorUnavailableError(_MSG_UNAVAILABLE)
        return ConnectorError(_MSG_REQUEST_FAILED)
    if isinstance(error, request_error):
        return ConnectorUnavailableError(_MSG_UNAVAILABLE)
    if isinstance(error, ConnectorError):
        return error
    return ConnectorError(_MSG_REQUEST_FAILED)


_PROJECT_V2_ORG_LOOKUP_QUERY = """
query KernectorProjectOrgLookup($login: String!, $number: Int!) {
  organization(login: $login) {
    projectV2(number: $number) { id }
  }
}
"""

_PROJECT_V2_USER_LOOKUP_QUERY = """
query KernectorProjectUserLookup($login: String!, $number: Int!) {
  user(login: $login) {
    projectV2(number: $number) { id }
  }
}
"""


def _is_soft_lookup_miss(errors: object) -> bool:
    """Return True when every GraphQL error is a login/permission miss."""
    if not isinstance(errors, Sequence) or isinstance(errors, (str, bytes)):
        return False
    if not errors:
        return False
    for error in errors:
        if not isinstance(error, Mapping):
            return False
        error_type = error.get("type")
        if error_type not in {"NOT_FOUND", "FORBIDDEN"}:
            return False
    return True

_PROJECT_V2_ITEMS_QUERY = """
query KernectorProjectItems($projectId: ID!, $first: Int!, $after: String) {
  node(id: $projectId) {
    __typename
    ... on ProjectV2 {
      items(first: $first, after: $after) {
        nodes {
          content {
            __typename
            ... on Issue {
              id
              number
              title
              body
              state
              url
              createdAt
              updatedAt
              closedAt
              labels(first: 50) { nodes { name } }
              assignees(first: 50) { nodes { login } }
              milestone { title }
              repository { nameWithOwner }
              comments(first: 100) {
                nodes { author { login } body createdAt updatedAt url }
              }
            }
            ... on PullRequest { id }
            ... on Discussion { id }
            ... on DraftIssue { id }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
