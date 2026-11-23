"""Jira artifact descriptor extractor (#373)."""

from __future__ import annotations

import pytest

from domain.artifact.kinds import ArtifactKind
from domain.knowledge import SourceDocument, SourceMetadata, SourceReference, SourceType
from infrastructure.connectors.jira.artifact_extractor import (
    DEFAULT_JIRA_KIND_MAP,
    JiraArtifactDescriptorExtractor,
)


def _jira_document(
    *,
    key: str = "PROJ-123",
    issue_type: str = "Story",
    title: str | None = None,
) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            reference=SourceReference(
                f"cloud-abc/PROJ:{key}", SourceType.JIRA
            ),
            title=title or f"{key}: Customer can cancel an unpaid order",
            provider="jira",
            content_format="markdown",
            extra={
                "jira_issue_key": key,
                "jira_issue_type": issue_type,
                "jira_issue_url": f"https://example.atlassian.net/browse/{key}",
                "jira_project_key": "PROJ",
                "jira_updated_at": "2026-01-15T12:00:00.000+0000",
                "connector_id": "jira-1",
            },
        ),
        f"# {key}\n\n- Type: {issue_type}\n",
    )


def test_story_maps_to_story_kind_with_issue_key() -> None:
    extractor = JiraArtifactDescriptorExtractor()

    descriptor = extractor.describe(_jira_document(key="PROJ-123", issue_type="Story"))

    assert descriptor is not None
    assert descriptor.kind == ArtifactKind.STORY
    assert descriptor.external_keys == ("PROJ-123",)
    assert descriptor.revision == "2026-01-15T12:00:00.000+0000"
    assert descriptor.title == "PROJ-123: Customer can cancel an unpaid order"
    assert descriptor.url == "https://example.atlassian.net/browse/PROJ-123"


def test_bug_and_test_default_mapping() -> None:
    extractor = JiraArtifactDescriptorExtractor()

    bug = extractor.describe(_jira_document(key="PROJ-130", issue_type="Bug"))
    test = extractor.describe(_jira_document(key="PROJ-140", issue_type="Test"))

    assert bug is not None and bug.kind == ArtifactKind.BUG
    assert test is not None and test.kind == ArtifactKind.TEST_CASE


def test_unmapped_issue_type_falls_back_to_work_item() -> None:
    extractor = JiraArtifactDescriptorExtractor()

    descriptor = extractor.describe(
        _jira_document(key="PROJ-200", issue_type="Epic")
    )

    assert descriptor is not None
    assert descriptor.kind == ArtifactKind.WORK_ITEM
    assert descriptor.external_keys == ("PROJ-200",)


def test_kind_map_is_configurable() -> None:
    extractor = JiraArtifactDescriptorExtractor(
        kind_map={"Epic": ArtifactKind.STORY, **DEFAULT_JIRA_KIND_MAP}
    )

    descriptor = extractor.describe(
        _jira_document(key="PROJ-201", issue_type="Epic")
    )

    assert descriptor is not None
    assert descriptor.kind == ArtifactKind.STORY


def test_non_jira_document_returns_none() -> None:
    extractor = JiraArtifactDescriptorExtractor()
    document = SourceDocument(
        SourceMetadata(
            reference=SourceReference("doc-1", SourceType.KNOWLEDGE_DOCUMENT),
            title="notes",
        ),
        "hello",
    )

    assert extractor.describe(document) is None


def test_missing_issue_key_returns_none() -> None:
    extractor = JiraArtifactDescriptorExtractor()
    document = SourceDocument(
        SourceMetadata(
            reference=SourceReference("cloud-abc/PROJ:X", SourceType.JIRA),
            title="X",
            extra={"jira_issue_type": "Story", "jira_updated_at": "r1"},
        ),
        "body",
    )

    assert extractor.describe(document) is None


@pytest.mark.parametrize(
    "issue_type,kind",
    [
        ("Story", ArtifactKind.STORY),
        ("Bug", ArtifactKind.BUG),
        ("Test", ArtifactKind.TEST_CASE),
    ],
)
def test_default_map_covers_fixture_types(issue_type: str, kind: str) -> None:
    assert DEFAULT_JIRA_KIND_MAP[issue_type] == kind
