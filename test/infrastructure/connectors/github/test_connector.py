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
    issue_doc = _doc("I_kwDO", "issue")
    repo = FakeAdapter([repo_doc])
    issues = FakeAdapter([issue_doc])
    connector = GitHubKnowledgeConnector(repo_documents=repo, issue_documents=issues)  # type: ignore[arg-type]

    assert connector.list_documents() == (repo_doc, issue_doc)
    assert connector.fetch_document(repo_doc).content == "content for octo/hello:README.md"
    assert connector.fetch_document(issue_doc).content == "content for I_kwDO"
    assert repo.fetches == ["octo/hello:README.md"]
    assert issues.fetches == ["I_kwDO"]


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
