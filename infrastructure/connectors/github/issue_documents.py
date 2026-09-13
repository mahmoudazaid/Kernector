"""ProjectV2 issue adapter for GitHub knowledge documents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from domain.errors import ConnectorError
from domain.knowledge import (
    ConnectorDocument,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.connectors.github.client import GitHubClient

_MSG_REQUEST_FAILED = "The GitHub request failed."
ISSUE_SOURCE_ID_PREFIX = "issue:"


@dataclass(frozen=True, slots=True)
class GitHubIssueConfig:
    """ProjectV2 issue ingestion configuration."""

    project_node_id: str
    include_comments: bool = False
    connector_id: str | None = None


class GitHubIssueDocuments:
    """Map ProjectV2 linked Issues to markdown source documents."""

    def __init__(self, client: GitHubClient, config: GitHubIssueConfig) -> None:
        self._client = client
        self._config = config
        self._issues_by_id: dict[str, Mapping[str, object]] | None = None

    def list_documents(self) -> Sequence[ConnectorDocument]:
        issues = self._load_issues()
        documents: list[ConnectorDocument] = []
        for source_id, content in issues.items():
            number = _required_int(content, "number")
            documents.append(
                ConnectorDocument(
                    reference=SourceReference(source_id, SourceType.GITHUB),
                    file_name=f"issue-{number}.md",
                    revision=_required_text(content, "updatedAt"),
                    extra={
                        "github_kind": "issue",
                        "project_node_id": self._config.project_node_id,
                        "number": str(number),
                        "url": _optional_text(content.get("url")) or "",
                        **_connector_extra(self._config.connector_id),
                    },
                )
            )
        return tuple(documents)

    def fetch_document(self, document: ConnectorDocument) -> SourceDocument:
        issue = self._find_issue(document.source_id)
        return SourceDocument(
            SourceMetadata(
                reference=document.reference,
                title=_required_text(issue, "title"),
                provider="github",
                content_format="markdown",
                extra={
                    "file_name": document.file_name,
                    "github_issue_id": document.source_id,
                    "github_issue_number": str(_required_int(issue, "number")),
                    "github_issue_url": _optional_text(issue.get("url")) or "",
                    "github_repository": _repository_name(issue),
                    "github_updated_at": _required_text(issue, "updatedAt"),
                    **_connector_extra(self._config.connector_id),
                },
            ),
            _markdown_for_issue(issue, include_comments=self._config.include_comments),
        )

    def _find_issue(self, source_id: str) -> Mapping[str, object]:
        cached = self._issues_by_id
        if cached is not None and source_id in cached:
            return cached[source_id]
        issues = self._load_issues(force=True)
        issue = issues.get(source_id)
        if issue is None:
            raise ConnectorError(_MSG_REQUEST_FAILED)
        return issue

    def _load_issues(self, *, force: bool = False) -> dict[str, Mapping[str, object]]:
        if self._issues_by_id is not None and not force:
            return self._issues_by_id
        issues: dict[str, Mapping[str, object]] = {}
        for content in self._client.get_project_v2_items(self._config.project_node_id):
            if content.get("__typename") != "Issue":
                continue
            node_id = _required_text(content, "id")
            issues[f"{ISSUE_SOURCE_ID_PREFIX}{node_id}"] = content
        self._issues_by_id = issues
        return issues


def _markdown_for_issue(
    issue: Mapping[str, object],
    *,
    include_comments: bool,
) -> str:
    title = _required_text(issue, "title")
    lines = [
        f"# {title}",
        "",
        f"- State: {_optional_text(issue.get('state')) or 'unknown'}",
        f"- Repository: {_repository_name(issue)}",
        f"- URL: {_optional_text(issue.get('url')) or ''}",
        f"- Created: {_optional_text(issue.get('createdAt')) or ''}",
        f"- Updated: {_required_text(issue, 'updatedAt')}",
        f"- Closed: {_optional_text(issue.get('closedAt')) or ''}",
        f"- Labels: {', '.join(_names_from_connection(issue.get('labels'), 'name'))}",
        f"- Assignees: {', '.join(_names_from_connection(issue.get('assignees'), 'login'))}",
        f"- Milestone: {_milestone(issue)}",
        "",
        "## Body",
        "",
        _optional_text(issue.get("body")) or "",
    ]
    if include_comments:
        comments = _comments(issue.get("comments"))
        if comments:
            lines.extend(["", "## Comments", ""])
            lines.extend(comments)
    return "\n".join(lines).strip() or title


def _comments(raw: object) -> list[str]:
    comments: list[str] = []
    for comment in _connection_nodes(raw):
        if not isinstance(comment, Mapping):
            continue
        author = _nested_optional_text(comment, ("author", "login")) or "unknown"
        created = _optional_text(comment.get("createdAt")) or ""
        updated = _optional_text(comment.get("updatedAt")) or ""
        url = _optional_text(comment.get("url")) or ""
        body = _optional_text(comment.get("body")) or ""
        comments.append(
            "\n".join(
                [
                    f"### Comment by {author}",
                    "",
                    f"- URL: {url}",
                    f"- Created: {created}",
                    f"- Updated: {updated}",
                    "",
                    body,
                    "",
                ]
            ).strip()
        )
    return comments


def _repository_name(issue: Mapping[str, object]) -> str:
    return _nested_optional_text(issue, ("repository", "nameWithOwner")) or ""


def _connector_extra(connector_id: str | None) -> dict[str, str]:
    if isinstance(connector_id, str) and connector_id.strip():
        return {"connector_id": connector_id.strip()}
    return {}


def _milestone(issue: Mapping[str, object]) -> str:
    return _nested_optional_text(issue, ("milestone", "title")) or ""


def _names_from_connection(raw: object, field: str) -> tuple[str, ...]:
    names: list[str] = []
    for node in _connection_nodes(raw):
        if isinstance(node, Mapping):
            value = _optional_text(node.get(field))
            if value:
                names.append(value)
    return tuple(names)


def _connection_nodes(raw: object) -> Sequence[object]:
    if not isinstance(raw, Mapping):
        return ()
    nodes = raw.get("nodes")
    if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
        return ()
    return nodes


def _nested_optional_text(raw: Mapping[str, object], keys: Sequence[str]) -> str | None:
    current: object = raw
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return _optional_text(current)


def _required_text(entry: Mapping[str, object], field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConnectorError(_MSG_REQUEST_FAILED)
    return value


def _optional_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _required_int(entry: Mapping[str, object], field: str) -> int:
    value = entry.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConnectorError(_MSG_REQUEST_FAILED)
    return value
