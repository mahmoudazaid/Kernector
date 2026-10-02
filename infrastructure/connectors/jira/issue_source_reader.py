"""Live Jira Data Center issue -> ``SourceDocument`` adapter (REST Get Issue).

The rendered document carries only the summary, description and acceptance
criteria: no instance URL, timestamps or raw payload fields.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from domain.errors import ConnectorError
from domain.knowledge import (
    SourceDocument,
    SourceLocator,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.connectors.jira.issue_locator import is_jira_issue_key
from infrastructure.connectors.jira.wiki import wiki_to_markdown

ISSUE_SOURCE_ID_PREFIX = "issue:"

_BASE_FIELDS = ("summary", "description", "updated")
_MSG_UNSUPPORTED_PROVIDER = "Live source provider is not supported."
_MSG_INVALID_PAYLOAD = "Jira issue response did not match the requested locator."
_MSG_EMPTY_EVIDENCE = "Jira issue has no description or acceptance criteria."


class JiraIssuePayloadError(ConnectorError):
    """The issue response is malformed or does not match the requested key."""


class JiraIssueEmptyEvidenceError(ConnectorError):
    """The issue exists but has no description or acceptance criteria text."""


class JiraDataCenterIssueClient(Protocol):
    """The single Jira call the issue reader needs."""

    def get_issue(self, key: str, fields: Sequence[str]) -> Mapping[str, object]: ...


class JiraDataCenterIssueSourceReader:
    """``LiveSourceReader`` for a single Jira Data Center issue."""

    def __init__(
        self,
        client: JiraDataCenterIssueClient,
        *,
        acceptance_criteria_field: str | None = None,
    ) -> None:
        self._client = client
        self._acceptance_criteria_field = acceptance_criteria_field

    def fetch(self, locator: SourceLocator) -> SourceDocument:
        if locator.provider.strip().casefold() != "jira":
            raise ConnectorError(_MSG_UNSUPPORTED_PROVIDER)
        key = locator.locator
        if not is_jira_issue_key(key):
            raise JiraIssuePayloadError(_MSG_INVALID_PAYLOAD)
        fields = _BASE_FIELDS + (
            (self._acceptance_criteria_field,) if self._acceptance_criteria_field else ()
        )
        payload = self._client.get_issue(key, fields)
        return issue_payload_to_source_document(
            payload,
            expected_key=key,
            acceptance_criteria_field=self._acceptance_criteria_field,
        )


def issue_payload_to_source_document(
    payload: Mapping[str, object],
    *,
    expected_key: str,
    acceptance_criteria_field: str | None = None,
) -> SourceDocument:
    """Map a REST issue payload to a ``SourceDocument``.

    Raises:
        JiraIssuePayloadError: Malformed payload, or key/id not matching.
        JiraIssueEmptyEvidenceError: Description and acceptance criteria are blank.
    """
    if not isinstance(payload, Mapping):
        raise JiraIssuePayloadError(_MSG_INVALID_PAYLOAD)
    key = payload.get("key")
    if not isinstance(key, str) or key.strip().upper() != expected_key:
        raise JiraIssuePayloadError(_MSG_INVALID_PAYLOAD)
    issue_id = payload.get("id")
    if not isinstance(issue_id, str) or not (issue_id.isascii() and issue_id.isdigit()):
        raise JiraIssuePayloadError(_MSG_INVALID_PAYLOAD)
    fields = payload.get("fields")
    if not isinstance(fields, Mapping):
        raise JiraIssuePayloadError(_MSG_INVALID_PAYLOAD)
    summary = fields.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise JiraIssuePayloadError(_MSG_INVALID_PAYLOAD)
    raw_description = fields.get("description")
    if raw_description is not None and not isinstance(raw_description, str):
        raise JiraIssuePayloadError(_MSG_INVALID_PAYLOAD)
    description = wiki_to_markdown(raw_description).strip()
    acceptance_criteria = (
        wiki_to_markdown(fields.get(acceptance_criteria_field)).strip()
        if acceptance_criteria_field
        else ""
    )
    if not description and not acceptance_criteria:
        raise JiraIssueEmptyEvidenceError(_MSG_EMPTY_EVIDENCE)
    updated = fields.get("updated")
    revision = updated.strip() if isinstance(updated, str) else ""
    title = f"{expected_key}: {summary.strip()}"
    return SourceDocument(
        SourceMetadata(
            reference=SourceReference(
                f"{ISSUE_SOURCE_ID_PREFIX}{issue_id}", SourceType.JIRA
            ),
            title=title,
            provider="jira",
            content_format="markdown",
            extra={
                "jira_issue_key": expected_key,
                "jira_issue_id": issue_id,
                "revision": revision,
            },
        ),
        _markdown(title, description, acceptance_criteria),
    )


def _markdown(title: str, description: str, acceptance_criteria: str) -> str:
    lines = [f"# {title}"]
    if description:
        lines.extend(["", "## Description", "", description])
    if acceptance_criteria:
        lines.extend(["", "## Acceptance criteria", "", acceptance_criteria])
    return "\n".join(lines)
