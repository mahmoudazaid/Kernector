"""GitHub ProjectV2 issue document adapter tests."""

from __future__ import annotations

from domain.knowledge import SourceType
from infrastructure.connectors.github.issue_documents import (
    GitHubIssueConfig,
    GitHubIssueDocuments,
)


class FakeGitHubClient:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self.items = items
        self.project_calls: list[str] = []

    def resolve_commit_sha(self, owner: str, repo: str, ref: str) -> str:
        return "commit"

    def get_git_tree(
        self,
        owner: str,
        repo: str,
        tree_sha: str,
        *,
        recursive: bool = True,
    ) -> dict[str, object]:
        return {"tree": []}

    def get_blob_content(self, owner: str, repo: str, blob_sha: str) -> bytes:
        return b""

    def get_project_v2_items(self, project_node_id: str) -> list[dict[str, object]]:
        self.project_calls.append(project_node_id)
        return list(self.items)


def _issue(**overrides: object) -> dict[str, object]:
    issue: dict[str, object] = {
        "__typename": "Issue",
        "id": "I_kwDO",
        "number": 42,
        "title": "Fix ingestion",
        "body": "The sync misses files.",
        "state": "OPEN",
        "url": "https://github.com/octo/hello/issues/42",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "closedAt": None,
        "labels": {"nodes": [{"name": "bug"}, {"name": "sync"}]},
        "assignees": {"nodes": [{"login": "mona"}]},
        "milestone": {"title": "v1"},
        "repository": {"nameWithOwner": "octo/hello"},
        "comments": {
            "nodes": [
                {
                    "author": {"login": "hubot"},
                    "body": "I can reproduce this.",
                    "createdAt": "2026-01-03T00:00:00Z",
                    "updatedAt": "2026-01-03T01:00:00Z",
                    "url": "https://github.com/octo/hello/issues/42#issuecomment-1",
                }
            ]
        },
    }
    issue.update(overrides)
    return issue


def test_lists_only_project_v2_linked_issues() -> None:
    client = FakeGitHubClient(
        [
            _issue(),
            {"__typename": "PullRequest", "id": "PR_1"},
            {"__typename": "DraftIssue", "id": "DI_1"},
            {"__typename": "Discussion", "id": "D_1"},
        ]
    )
    adapter = GitHubIssueDocuments(client, GitHubIssueConfig(project_node_id="PVT_1"))

    docs = adapter.list_documents()

    assert len(docs) == 1
    assert docs[0].source_id == "I_kwDO"
    assert docs[0].reference.source_type == SourceType.GITHUB
    assert docs[0].revision == "2026-01-02T00:00:00Z"
    assert docs[0].file_name == "issue-42.md"
    assert docs[0].extra["github_kind"] == "issue"


def test_fetch_renders_issue_markdown_without_comments_by_default() -> None:
    client = FakeGitHubClient([_issue()])
    adapter = GitHubIssueDocuments(client, GitHubIssueConfig(project_node_id="PVT_1"))
    listed = adapter.list_documents()[0]

    source = adapter.fetch_document(listed)

    assert source.metadata.provider == "github"
    assert source.metadata.content_format == "markdown"
    assert source.metadata.extra["github_repository"] == "octo/hello"
    assert "# Fix ingestion" in source.content
    assert "- State: OPEN" in source.content
    assert "- Labels: bug, sync" in source.content
    assert "- Assignees: mona" in source.content
    assert "- Milestone: v1" in source.content
    assert "The sync misses files." in source.content
    assert "I can reproduce this." not in source.content


def test_fetch_includes_comments_when_configured() -> None:
    client = FakeGitHubClient([_issue()])
    adapter = GitHubIssueDocuments(
        client,
        GitHubIssueConfig(project_node_id="PVT_1", include_comments=True),
    )
    listed = adapter.list_documents()[0]

    source = adapter.fetch_document(listed)

    assert "## Comments" in source.content
    assert "### Comment by hubot" in source.content
    assert "I can reproduce this." in source.content
