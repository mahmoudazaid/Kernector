"""Jira issue → ArtifactDescriptor (kind mapping and external keys)."""

from __future__ import annotations

from collections.abc import Mapping

from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor
from domain.knowledge import SourceDocument, SourceType

DEFAULT_JIRA_KIND_MAP: dict[str, str] = {
    "Story": ArtifactKind.STORY,
    "Bug": ArtifactKind.BUG,
    "Test": ArtifactKind.TEST_CASE,
}


class JiraArtifactDescriptorExtractor:
    """Map Jira issue type to artifact kind; external key is the issue key."""

    def __init__(
        self, *, kind_map: Mapping[str, str] | None = None
    ) -> None:
        self._kind_map = dict(kind_map) if kind_map is not None else dict(
            DEFAULT_JIRA_KIND_MAP
        )

    def describe(self, document: SourceDocument) -> ArtifactDescriptor | None:
        if document.reference.source_type != SourceType.JIRA:
            return None
        extra = document.metadata.extra
        issue_key = extra.get("jira_issue_key")
        if not isinstance(issue_key, str) or not issue_key.strip():
            return None
        revision = extra.get("jira_updated_at")
        if not isinstance(revision, str) or not revision.strip():
            return None
        issue_type = extra.get("jira_issue_type", "")
        kind = self._kind_map.get(
            issue_type if isinstance(issue_type, str) else "",
            ArtifactKind.WORK_ITEM,
        )
        url = extra.get("jira_issue_url")
        return ArtifactDescriptor(
            reference=document.reference,
            revision=revision,
            kind=kind,
            external_keys=(issue_key.strip(),),
            title=document.metadata.title,
            url=url if isinstance(url, str) and url.strip() else None,
        )
