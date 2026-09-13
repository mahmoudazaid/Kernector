"""Combined GitHub connector and HTTP client behavior tests."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from domain.errors import ConnectorAuthError, ConnectorUnavailableError
from domain.knowledge import (
    ConnectorDocument,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.connectors.github.client import HttpGitHubClient
from infrastructure.connectors.github.connector import GitHubKnowledgeConnector

SECRET = "ghp_SECRET_SHOULD_NOT_LEAK"


class FakeAdapter:
    def __init__(
        self,
        documents: list[ConnectorDocument],
        *,
        error: BaseException | None = None,
    ) -> None:
        self.documents = documents
        self.error = error
        self.fetches: list[str] = []

    def list_documents(self) -> list[ConnectorDocument]:
        if self.error is not None:
            raise self.error
        return self.documents

    def fetch_document(self, document: ConnectorDocument) -> SourceDocument:
        self.fetches.append(document.source_id)
        return SourceDocument(
            SourceMetadata(
                reference=document.reference,
                title=document.file_name,
                provider="github",
                content_format="markdown",
            ),
            f"content for {document.source_id}",
        )


def _doc(source_id: str, kind: str) -> ConnectorDocument:
    return ConnectorDocument(
        SourceReference(source_id, SourceType.GITHUB),
        "item.md",
        "rev",
        {"github_kind": kind},
    )


def test_combined_connector_merges_and_dispatches_documents() -> None:
    repo_doc = _doc("octo/hello:README.md", "repo")
    issue_doc = _doc("issue:I_kwDO", "issue")
    repo = FakeAdapter([repo_doc])
    issues = FakeAdapter([issue_doc])
    connector = GitHubKnowledgeConnector(repo_documents=repo, issue_documents=issues)  # type: ignore[arg-type]

    assert connector.list_documents() == (repo_doc, issue_doc)
    assert connector.fetch_document(repo_doc).content == "content for octo/hello:README.md"
    assert connector.fetch_document(issue_doc).content == "content for issue:I_kwDO"
    assert repo.fetches == ["octo/hello:README.md"]
    assert issues.fetches == ["issue:I_kwDO"]


def test_combined_connector_never_returns_partial_listing() -> None:
    repo_doc = _doc("octo/hello:README.md", "repo")
    connector = GitHubKnowledgeConnector(
        repo_documents=FakeAdapter([repo_doc]),  # type: ignore[arg-type]
        issue_documents=FakeAdapter(
            [],
            error=ConnectorUnavailableError("rate limited"),
        ),  # type: ignore[arg-type]
    )

    with pytest.raises(ConnectorUnavailableError, match="rate limited"):
        connector.list_documents()


def test_http_client_walks_project_pagination_fully() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append(body["variables"])
        after = body["variables"]["after"]
        return httpx.Response(
            200,
            json={
                "data": {
                    "node": {
                        "__typename": "ProjectV2",
                        "items": {
                            "nodes": [
                                {
                                    "content": {
                                        "__typename": "Issue",
                                        "id": f"issue-{after or 'first'}",
                                        "number": 1,
                                        "title": "Issue",
                                        "updatedAt": "2026-01-01T00:00:00Z",
                                    }
                                }
                            ],
                            "pageInfo": {
                                "hasNextPage": after is None,
                                "endCursor": "cursor-1" if after is None else None,
                            },
                        },
                    }
                }
            },
        )

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )

    items = client.get_project_v2_items("PVT_1")

    assert [item["id"] for item in items] == ["issue-first", "issue-cursor-1"]
    assert calls == [
        {"projectId": "PVT_1", "after": None, "first": 100},
        {"projectId": "PVT_1", "after": "cursor-1", "first": 100},
    ]


def test_http_client_mid_pagination_rate_limit_raises_without_partial() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 2:
            return httpx.Response(429, json={"message": SECRET})
        return httpx.Response(
            200,
            json={
                "data": {
                    "node": {
                        "__typename": "ProjectV2",
                        "items": {
                            "nodes": [{"content": {"__typename": "Issue", "id": "I_1"}}],
                            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                        },
                    }
                }
            },
        )

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ConnectorUnavailableError) as raised:
        client.get_project_v2_items("PVT_1")

    assert SECRET not in str(raised.value)
    assert calls == 2


def test_http_client_redacts_auth_error_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": SECRET})

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ConnectorAuthError) as raised:
        client.resolve_commit_sha("octo", "hello", "main")

    assert SECRET not in str(raised.value)


def test_http_client_maps_empty_repository_conflict() -> None:
    from infrastructure.connectors.github.client import GitHubEmptyRepositoryError

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/repos/octo/empty/commits/HEAD")
        return httpx.Response(
            409,
            json={"message": "Git Repository is empty.", "status": "409"},
        )

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(GitHubEmptyRepositoryError, match="no commits"):
        client.resolve_commit_sha("octo", "empty", "HEAD")


def test_http_client_decodes_blob_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/repos/octo/hello/git/blobs/blob-1")
        encoded = base64.b64encode(b"hello").decode("ascii")
        return httpx.Response(200, json={"content": encoded, "encoding": "base64"})

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )

    assert client.get_blob_content("octo", "hello", "blob-1") == b"hello"


def test_http_client_lists_repositories_and_projects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/user/repos"):
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "hello",
                        "full_name": "octo/hello",
                        "private": False,
                        "owner": {"login": "octo"},
                    }
                ],
            )
        body = json.loads(request.content.decode("utf-8"))
        if "projectsV2" in body["query"] and "organization" in body["query"]:
            return httpx.Response(
                200,
                json={
                    "data": {"organization": None},
                    "errors": [{"type": "NOT_FOUND", "path": ["organization"]}],
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "user": {
                        "projectsV2": {
                            "nodes": [{"number": 1, "title": "Board"}],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            },
        )

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    repos = client.list_repositories(page=1)
    assert repos["items"][0]["full_name"] == "octo/hello"
    assert repos["has_next"] is False
    projects = client.list_projects("octo")
    assert projects["items"][0]["number"] == 1
    assert projects["next_cursor"] is None


def test_resolve_project_v2_id_accepts_user_owned_partial_error() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        query = body["query"]
        calls.append("organization" if "organization" in query else "user")
        if "organization" in query:
            return httpx.Response(
                200,
                json={
                    "data": {"organization": None},
                    "errors": [
                        {
                            "type": "NOT_FOUND",
                            "path": ["organization"],
                            "message": "Could not resolve to an Organization with the login of 'ada'.",
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={"data": {"user": {"projectV2": {"id": "PVT_kwHOUserOwned"}}}},
        )

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )

    assert client.resolve_project_v2_id("ada", 3) == "PVT_kwHOUserOwned"
    assert calls == ["organization", "user"]


def test_resolve_project_v2_id_accepts_org_owned_partial_error() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        query = body["query"]
        calls.append("organization" if "organization" in query else "user")
        if "organization" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "organization": {"projectV2": {"id": "PVT_kwHOOrgOwned"}}
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {"user": None},
                "errors": [
                    {
                        "type": "NOT_FOUND",
                        "path": ["user"],
                        "message": "Could not resolve to a User with the login of 'acme'.",
                    }
                ],
            },
        )

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )

    assert client.resolve_project_v2_id("acme", 7) == "PVT_kwHOOrgOwned"
    assert calls == ["organization"]


def test_resolve_project_v2_id_accepts_forbidden_on_org_then_user() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        if "organization" in body["query"]:
            return httpx.Response(
                200,
                json={
                    "data": {"organization": None},
                    "errors": [
                        {
                            "type": "FORBIDDEN",
                            "path": ["organization"],
                            "message": "Although you appear to have the correct authorization credentials, the `acme` organization has enabled OAuth App access restrictions.",
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={"data": {"user": {"projectV2": {"id": "PVT_kwHOFallback"}}}},
        )

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )

    assert client.resolve_project_v2_id("acme", 1) == "PVT_kwHOFallback"


def test_settings_project_lookup_failure_is_config_error() -> None:
    from domain.errors import ConnectorError
    from infrastructure.connectors.github.connector import GitHubConnectorConfigError

    with pytest.raises(GitHubConnectorConfigError):
        GitHubKnowledgeConnector(
            _project_settings(),
            client=_lookup_client(ConnectorError("The GitHub request failed.")),  # type: ignore[arg-type]
        )


def test_settings_project_lookup_auth_error_propagates() -> None:
    from domain.errors import ConnectorAuthError

    with pytest.raises(ConnectorAuthError, match="expired"):
        GitHubKnowledgeConnector(
            _project_settings(),
            client=_lookup_client(ConnectorAuthError("expired")),  # type: ignore[arg-type]
        )


def test_settings_project_lookup_unavailable_error_propagates() -> None:
    from domain.errors import ConnectorUnavailableError

    with pytest.raises(ConnectorUnavailableError, match="rate limited"):
        GitHubKnowledgeConnector(
            _project_settings(),
            client=_lookup_client(ConnectorUnavailableError("rate limited")),  # type: ignore[arg-type]
        )


def _project_settings() -> object:
    from dataclasses import dataclass

    @dataclass
    class Settings:
        token: str = SECRET
        owner: str = "octo"
        repo: str = "hello"
        ref: str = "HEAD"
        include_paths: tuple[str, ...] = ()
        exclude_paths: tuple[str, ...] = ()
        extensions: tuple[str, ...] = (".md",)
        max_file_bytes: int = 1_000_000
        project_owner: str = "ada"
        project_number: int = 1
        include_issue_comments: bool = False
        page_size: int = 100

    return Settings()


def _lookup_client(error: BaseException) -> object:
    class FailingClient:
        def resolve_project_v2_id(self, owner_login: str, number: int) -> str:
            raise error

    return FailingClient()
