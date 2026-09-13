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
_MSG_EMPTY_REPOSITORY = "This GitHub repository has no commits yet."
_MSG_CONFIG = "GitHub connector optional dependency is missing; install kernector[github]."


class GitHubConfigError(RuntimeError):
    """GitHub connector settings or optional dependencies are unusable."""


class GitHubEmptyRepositoryError(ConnectorError):
    """The selected repository exists but has no commits to sync."""


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

    def get_repository(self, owner: str, repo: str) -> Mapping[str, object]:
        """Return one repository metadata payload."""
        ...

    def list_repositories(
        self,
        *,
        page: int = 1,
        per_page: int | None = None,
    ) -> Mapping[str, object]:
        """Return one page of repositories visible to the token.

        Payload shape: ``{"items": Sequence[Mapping], "has_next": bool}``.
        """
        ...

    def list_projects(
        self,
        owner_login: str,
        *,
        after: str | None = None,
        first: int | None = None,
    ) -> Mapping[str, object]:
        """Return one page of ProjectV2 projects for a user or organization.

        Payload shape: ``{"items": Sequence[Mapping], "next_cursor": str | None}``.
        Each item includes ``number``, ``title``, and ``owner_login``.
        """
        ...

    def get_project_v2_items(
        self,
        project_node_id: str,
    ) -> Sequence[Mapping[str, object]]:
        """Return all ProjectV2 item content nodes, walking all pages.

        Each Issue includes up to 100 comments. Page size is capped so nested
        comment fields stay within GitHub GraphQL complexity limits.
        """
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

    def get_repository(self, owner: str, repo: str) -> Mapping[str, object]:
        return self._get_json(f"/repos/{owner}/{repo}")

    def list_repositories(
        self,
        *,
        page: int = 1,
        per_page: int | None = None,
    ) -> Mapping[str, object]:
        size = self._page_size if per_page is None else per_page
        if page < 1 or size < 1:
            raise ConnectorError(_MSG_REQUEST_FAILED)
        payload = self._get_json_list(
            "/user/repos",
            params={
                "per_page": size,
                "page": page,
                "affiliation": "owner,collaborator,organization_member",
                "sort": "full_name",
            },
        )
        items: list[Mapping[str, object]] = []
        for row in payload:
            if not isinstance(row, Mapping):
                continue
            full_name = row.get("full_name")
            name = row.get("name")
            owner_payload = row.get("owner")
            owner_login = None
            if isinstance(owner_payload, Mapping):
                login = owner_payload.get("login")
                if isinstance(login, str) and login.strip():
                    owner_login = login.strip()
            if (
                isinstance(full_name, str)
                and full_name.strip()
                and isinstance(name, str)
                and name.strip()
                and owner_login
            ):
                items.append(
                    {
                        "owner": owner_login,
                        "name": name.strip(),
                        "full_name": full_name.strip(),
                        "private": bool(row.get("private")),
                    }
                )
        return {"items": tuple(items), "has_next": len(payload) >= size}

    def list_projects(
        self,
        owner_login: str,
        *,
        after: str | None = None,
        first: int | None = None,
    ) -> Mapping[str, object]:
        size = self._page_size if first is None else first
        if size < 1 or not owner_login.strip():
            raise ConnectorError(_MSG_REQUEST_FAILED)
        login = owner_login.strip()
        for query, root in (
            (_PROJECT_V2_ORG_LIST_QUERY, "organization"),
            (_PROJECT_V2_USER_LIST_QUERY, "user"),
        ):
            payload = self._graphql(
                query,
                {"login": login, "first": size, "after": after},
                soft_lookup_miss=True,
            )
            owner = _optional_nested_mapping(payload, ("data", root))
            if owner is None:
                continue
            page = owner.get("projectsV2")
            if not isinstance(page, Mapping):
                raise ConnectorError(_MSG_REQUEST_FAILED)
            nodes = page.get("nodes")
            if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
                raise ConnectorError(_MSG_REQUEST_FAILED)
            items: list[Mapping[str, object]] = []
            for node in nodes:
                if not isinstance(node, Mapping):
                    continue
                number = node.get("number")
                title = node.get("title")
                if isinstance(number, int) and isinstance(title, str) and title.strip():
                    items.append(
                        {
                            "number": number,
                            "title": title.strip(),
                            "owner_login": login,
                        }
                    )
            page_info = page.get("pageInfo")
            next_cursor: str | None = None
            if isinstance(page_info, Mapping) and page_info.get("hasNextPage") is True:
                end_cursor = page_info.get("endCursor")
                if isinstance(end_cursor, str) and end_cursor:
                    next_cursor = end_cursor
            return {"items": tuple(items), "next_cursor": next_cursor}
        return {"items": (), "next_cursor": None}

    def get_project_v2_items(
        self,
        project_node_id: str,
    ) -> Sequence[Mapping[str, object]]:
        items: list[Mapping[str, object]] = []
        after: str | None = None
        # Cap page size — nested comments(first:100) on a full page exceeds
        # GitHub GraphQL complexity limits.
        page_size = min(self._page_size, 20)
        while True:
            payload = self._graphql(
                _PROJECT_V2_ITEMS_QUERY,
                {
                    "projectId": project_node_id,
                    "after": after,
                    "first": page_size,
                },
            )
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

    def _get_json_list(
        self,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> Sequence[object]:
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception as error:
            raise _map_httpx_error(error, self._httpx) from error
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
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
            detail = _graphql_error_detail(errors)
            raise ConnectorError(detail or _MSG_REQUEST_FAILED)
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
        if status == 409:
            return GitHubEmptyRepositoryError(_MSG_EMPTY_REPOSITORY)
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

_PROJECT_V2_ORG_LIST_QUERY = """
query KernectorProjectOrgList($login: String!, $first: Int!, $after: String) {
  organization(login: $login) {
    projectsV2(first: $first, after: $after) {
      nodes { number title }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

_PROJECT_V2_USER_LIST_QUERY = """
query KernectorProjectUserList($login: String!, $first: Int!, $after: String) {
  user(login: $login) {
    projectsV2(first: $first, after: $after) {
      nodes { number title }
      pageInfo { hasNextPage endCursor }
    }
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


def _graphql_error_detail(errors: object) -> str | None:
    """Return a presentation-safe first GraphQL error message, if any."""
    if not isinstance(errors, Sequence) or isinstance(errors, (str, bytes)):
        return None
    for error in errors:
        if not isinstance(error, Mapping):
            continue
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return None


_ISSUE_CONTENT_FIELDS = """
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
            ... on DraftIssue { id }
"""

_PROJECT_V2_ITEMS_QUERY = f"""
query KernectorProjectItems($projectId: ID!, $first: Int!, $after: String) {{
  node(id: $projectId) {{
    __typename
    ... on ProjectV2 {{
      items(first: $first, after: $after) {{
        nodes {{
          content {{
{_ISSUE_CONTENT_FIELDS}
          }}
        }}
        pageInfo {{ hasNextPage endCursor }}
      }}
    }}
  }}
}}
"""
