"""Jira issue adapter for knowledge documents."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from domain.errors import ConnectorError
from domain.knowledge import (
    ConnectorDocument,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.connectors.jira.adf import adf_to_markdown
from infrastructure.connectors.jira.client import JiraClient
from infrastructure.connectors.jira.errors import (
    JiraIssueLimitExceededError,
    JiraPaginationError,
)
from infrastructure.connectors.jira.site import JiraSite

_MSG_REQUEST_FAILED = "The Jira request failed."
_ISSUE_FIELDS = (
    "summary",
    "description",
    "status",
    "issuetype",
    "priority",
    "labels",
    "assignee",
    "reporter",
    "components",
    "fixVersions",
    "parent",
    "created",
    "updated",
)


@dataclass(frozen=True, slots=True)
class JiraIssueConfig:
    """Issue ingestion scope for one Jira instance.

    ``render_text`` converts description and comment bodies to Markdown: ADF for
    Jira Cloud, wiki markup for Data Center.
    """

    site: JiraSite
    project_keys: tuple[str, ...]
    connector_id: str | None = None
    include_comments: bool = False
    page_size: int = 100
    max_issues: int = 5000
    render_text: Callable[[object], str] = adf_to_markdown
    deployment: Literal["cloud", "data_center"] = "cloud"


def project_source_id_prefix(instance_id: str, project_key: str) -> str:
    return f"{instance_id}/{project_key}:"


class JiraIssueDocuments:
    """Map selected-project Jira issues to markdown source documents."""

    def __init__(self, client: JiraClient, config: JiraIssueConfig) -> None:
        self._client = client
        self._config = config
        self._issues: dict[str, tuple[str, Mapping[str, object]]] | None = None

    def list_documents(self) -> Sequence[ConnectorDocument]:
        documents: list[ConnectorDocument] = []
        issues: dict[str, tuple[str, Mapping[str, object]]] = {}
        page_budget = _page_budget(self._config)
        pages_fetched = 0
        fields = self._fields()
        for project_key in self._config.project_keys:
            token: str | None = None
            seen_tokens: set[str] = set()
            first_total: int | None = None
            while True:
                if pages_fetched >= page_budget:
                    raise JiraPaginationError()
                page = self._client.search_issues(
                    _project_jql(project_key),
                    fields,
                    self._config.page_size,
                    token,
                )
                pages_fetched += 1
                if page.total is not None:
                    if first_total is None:
                        first_total = page.total
                    elif page.total != first_total:
                        raise JiraPaginationError()
                page_issues = page.issues
                if not isinstance(page_issues, Sequence) or isinstance(
                    page_issues, (str, bytes)
                ):
                    raise JiraPaginationError()
                for issue in page_issues:
                    if not isinstance(issue, Mapping):
                        raise JiraPaginationError()
                    document = self._document(project_key, issue)
                    if document.source_id in issues:
                        continue
                    issues[document.source_id] = (project_key, issue)
                    documents.append(document)
                if len(documents) > self._config.max_issues:
                    raise JiraIssueLimitExceededError()
                if page.is_last:
                    break
                token = _next_token(page.next_page_token, seen_tokens)
        self._issues = issues
        return tuple(documents)

    def fetch_document(self, document: ConnectorDocument) -> SourceDocument:
        if self._issues is None or document.source_id not in self._issues:
            self.list_documents()
        assert self._issues is not None
        entry = self._issues.get(document.source_id)
        if entry is None:
            raise ConnectorError(_MSG_REQUEST_FAILED)
        project_key, issue = entry
        key = _required_text(issue, "key")
        fields = _fields_of(issue)
        site = self._config.site
        summary = _required_text(fields, "summary")
        return SourceDocument(
            SourceMetadata(
                reference=document.reference,
                title=f"{key}: {summary}",
                provider="jira",
                content_format="markdown",
                extra={
                    "file_name": document.file_name,
                    **_connector_extra(self._config.connector_id),
                    "jira_issue_key": key,
                    "jira_issue_url": site.browse_url(key),
                    "jira_instance_id": site.instance_id,
                    "jira_project_key": project_key,
                    "jira_site_url": site.site_url,
                    "jira_updated_at": _required_text(fields, "updated"),
                },
            ),
            self._markdown(project_key, key, fields),
        )

    def _fields(self) -> tuple[str, ...]:
        if self._config.include_comments:
            return (*_ISSUE_FIELDS, "comment")
        return _ISSUE_FIELDS

    def _document(
        self, project_key: str, issue: Mapping[str, object]
    ) -> ConnectorDocument:
        key = _required_text(issue, "key")
        fields = _fields_of(issue)
        site = self._config.site
        source_id = f"{project_source_id_prefix(site.instance_id, project_key)}{key}"
        cloud_extra = (
            {"cloud_id": site.cloud_id} if self._config.deployment == "cloud" else {}
        )
        return ConnectorDocument(
            reference=SourceReference(source_id, SourceType.JIRA),
            file_name=f"{key}.md",
            revision=_required_text(fields, "updated"),
            extra={
                **_connector_extra(self._config.connector_id),
                **cloud_extra,
                "jira_instance_id": site.instance_id,
                "project_key": project_key,
                "issue_key": key,
                "url": site.browse_url(key),
            },
        )

    def _markdown(
        self, project_key: str, key: str, fields: Mapping[str, object]
    ) -> str:
        title = f"{key}: {_required_text(fields, 'summary')}"
        lines = [
            f"# {title}",
            "",
            f"- Key: {key}",
            f"- Project: {project_key}",
            f"- Type: {_name(fields.get('issuetype'))}",
        ]
        parent_key = _text(_mapping(fields.get("parent")).get("key"))
        if parent_key:
            lines.append(f"- Parent: {parent_key}")
        lines.extend(
            [
                f"- Status: {_name(fields.get('status'))}",
                f"- Priority: {_name(fields.get('priority'))}",
                f"- Labels: {', '.join(_texts(fields.get('labels')))}",
                f"- Assignee: {_display_name(fields.get('assignee'))}",
                f"- Reporter: {_display_name(fields.get('reporter'))}",
                f"- Components: {', '.join(_names(fields.get('components')))}",
                f"- Fix versions: {', '.join(_names(fields.get('fixVersions')))}",
                f"- URL: {self._config.site.browse_url(key)}",
                f"- Created: {_text(fields.get('created'))}",
                f"- Updated: {_required_text(fields, 'updated')}",
            ]
        )
        description = self._config.render_text(fields.get("description"))
        if description:
            lines.extend(["", "## Description", "", description])
        if self._config.include_comments:
            comments = _comments(fields.get("comment"), self._config.render_text)
            if comments:
                lines.extend(["", "## Comments", ""])
                lines.extend(comments)
        return "\n".join(lines).strip()


def _comments(raw: object, render_text: Callable[[object], str]) -> list[str]:
    entries = _mapping(raw).get("comments")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        return []
    rendered: list[str] = []
    for comment in entries:
        if not isinstance(comment, Mapping):
            continue
        body = render_text(comment.get("body"))
        author = _display_name(comment.get("author")) or "unknown"
        rendered.append(
            "\n".join(
                [
                    f"### Comment by {author}",
                    "",
                    f"- Created: {_text(comment.get('created'))}",
                    "",
                    body,
                    "",
                ]
            ).strip()
        )
    return rendered


def _page_budget(config: JiraIssueConfig) -> int:
    # Every selected project needs at least one (possibly empty) last page.
    return -(-config.max_issues // config.page_size) + len(config.project_keys)


def _next_token(raw: str | None, seen: set[str]) -> str:
    if not isinstance(raw, str) or not raw.strip() or raw in seen:
        raise JiraPaginationError()
    seen.add(raw)
    return raw


def _project_jql(project_key: str) -> str:
    return f'project = "{project_key}" ORDER BY key ASC'


def _connector_extra(connector_id: str | None) -> dict[str, str]:
    if isinstance(connector_id, str) and connector_id.strip():
        return {"connector_id": connector_id.strip()}
    return {}


def _fields_of(issue: Mapping[str, object]) -> Mapping[str, object]:
    fields = issue.get("fields")
    if not isinstance(fields, Mapping):
        raise ConnectorError(_MSG_REQUEST_FAILED)
    return fields


def _mapping(raw: object) -> Mapping[str, object]:
    return raw if isinstance(raw, Mapping) else {}


def _text(raw: object) -> str:
    return raw if isinstance(raw, str) else ""


def _name(raw: object) -> str:
    return _text(_mapping(raw).get("name"))


def _display_name(raw: object) -> str:
    return _text(_mapping(raw).get("displayName"))


def _texts(raw: object) -> list[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [item for item in raw if isinstance(item, str) and item]


def _names(raw: object) -> list[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [name for name in (_name(item) for item in raw) if name]


def _required_text(entry: Mapping[str, object], field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConnectorError(_MSG_REQUEST_FAILED)
    return value
