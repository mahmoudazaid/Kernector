"""GitHub repository document adapter tests."""

from __future__ import annotations

import pytest

from domain.errors import ConnectorError, ConnectorUnavailableError
from domain.knowledge import SourceType
from infrastructure.connectors.github.repo_documents import (
    GitHubRepoConfig,
    GitHubRepoDocuments,
)


class FakeGitHubClient:
    def __init__(
        self,
        *,
        tree: list[dict[str, object]],
        blobs: dict[str, bytes] | None = None,
    ) -> None:
        self.tree = tree
        self.blobs = blobs or {}
        self.resolved: list[tuple[str, str, str]] = []
        self.tree_calls: list[tuple[str, str, str]] = []
        self.blob_calls: list[str] = []

    def resolve_commit_sha(self, owner: str, repo: str, ref: str) -> str:
        self.resolved.append((owner, repo, ref))
        return "commit-sha"

    def get_git_tree(
        self,
        owner: str,
        repo: str,
        tree_sha: str,
        *,
        recursive: bool = True,
    ) -> dict[str, object]:
        self.tree_calls.append((owner, repo, tree_sha))
        return {"tree": self.tree, "truncated": False}

    def get_blob_content(self, owner: str, repo: str, blob_sha: str) -> bytes:
        self.blob_calls.append(blob_sha)
        return self.blobs[blob_sha]

    def get_project_v2_items(self, project_node_id: str) -> list[dict[str, object]]:
        return []

    def resolve_project_v2_id(self, owner_login: str, number: int) -> str:
        return f"PVT_{owner_login}_{number}"


def test_lists_supported_repo_blobs_with_commit_provenance() -> None:
    client = FakeGitHubClient(
        tree=[
            {"type": "blob", "path": "docs/readme.md", "sha": "blob-1", "size": 20},
            {"type": "blob", "path": "src/app.py", "sha": "blob-2", "size": 30},
            {"type": "blob", "path": "node_modules/pkg/index.md", "sha": "skip-1", "size": 5},
            {"type": "blob", "path": "dist/bundle.txt", "sha": "skip-2", "size": 5},
            {"type": "blob", "path": "docs/logo.png", "sha": "skip-3", "size": 5},
            {"type": "blob", "path": "docs/huge.md", "sha": "skip-4", "size": 2_000},
            {"type": "tree", "path": "docs", "sha": "skip-tree"},
        ]
    )
    adapter = GitHubRepoDocuments(
        client,
        GitHubRepoConfig(
            owner="octo",
            repo="hello",
            ref="main",
            include_prefixes=("docs/",),
            max_size_bytes=100,
        ),
    )

    docs = adapter.list_documents()

    assert [doc.source_id for doc in docs] == ["octo/hello:docs/readme.md"]
    assert docs[0].reference.source_type == SourceType.GITHUB
    assert docs[0].revision == "blob-1"
    assert docs[0].extra["url"] == (
        "https://github.com/octo/hello/blob/commit-sha/docs/readme.md"
    )
    assert client.resolved == [("octo", "hello", "main")]
    assert client.tree_calls == [("octo", "hello", "commit-sha")]


def test_fetches_repo_blob_as_source_document() -> None:
    client = FakeGitHubClient(
        tree=[{"type": "blob", "path": "docs/readme.md", "sha": "blob-1", "size": 11}],
        blobs={"blob-1": b"hello world"},
    )
    adapter = GitHubRepoDocuments(client, GitHubRepoConfig(owner="octo", repo="hello"))
    listed = adapter.list_documents()[0]

    source = adapter.fetch_document(listed)

    assert source.content == "hello world"
    assert source.metadata.provider == "github"
    assert source.metadata.content_format == "markdown"
    assert source.metadata.extra["github_commit_sha"] == "commit-sha"
    assert source.metadata.extra["github_blob_sha"] == "blob-1"
    assert source.metadata.extra["github_url"] == (
        "https://github.com/octo/hello/blob/commit-sha/docs/readme.md"
    )


def test_rejects_non_utf8_blob_without_provider_detail() -> None:
    client = FakeGitHubClient(
        tree=[{"type": "blob", "path": "docs/readme.md", "sha": "blob-1", "size": 3}],
        blobs={"blob-1": b"\xff\xfe\xff"},
    )
    adapter = GitHubRepoDocuments(client, GitHubRepoConfig(owner="octo", repo="hello"))
    listed = adapter.list_documents()[0]

    with pytest.raises(ConnectorError, match="could not be read as text"):
        adapter.fetch_document(listed)


def test_propagates_truncated_tree_as_unavailable() -> None:
    class TruncatedClient(FakeGitHubClient):
        def get_git_tree(
            self,
            owner: str,
            repo: str,
            tree_sha: str,
            *,
            recursive: bool = True,
        ) -> dict[str, object]:
            raise ConnectorUnavailableError("GitHub returned an incomplete repository listing.")

    adapter = GitHubRepoDocuments(
        TruncatedClient(tree=[]),
        GitHubRepoConfig(owner="octo", repo="hello"),
    )

    with pytest.raises(ConnectorUnavailableError):
        adapter.list_documents()
