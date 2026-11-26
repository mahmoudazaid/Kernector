"""Configured Jira link-type mapping and mapping fingerprint (#374)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from application.relationship.record import RecordExplicitRelationships
from composition.relationship.container import _jira_link_mapping
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.artifact.sql_index import SqlArtifactIndex
from infrastructure.config import load_settings
from infrastructure.connectors.jira.link_extractor import (
    PROVIDER_LINKS_EXTRA_KEY,
    JiraExplicitLinkExtractor,
    decode_provider_links_raw,
    encode_provider_links,
)
from infrastructure.relationship.sql_store import SqlRelationshipStore


def _settings_with_link_type(link_type: str):
    settings = load_settings()
    return replace(settings, xray=replace(settings.xray, link_type=link_type))


def test_xray_link_type_relates_does_not_overwrite_default() -> None:
    mapping = _jira_link_mapping(_settings_with_link_type("Relates"))
    assert mapping.by_name["relates"] == ("relates_to", "subject")


def test_custom_xray_link_type_maps_to_tests() -> None:
    mapping = _jira_link_mapping(_settings_with_link_type("Verified By"))
    assert mapping.by_name["verified by"] == ("tests", "subject")


def test_mapping_fingerprint_change_rerecords_unchanged_issue(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite"
    store = SqlRelationshipStore(path, "ws-a")
    index = SqlArtifactIndex(path, "ws-a")
    index.upsert(
        ArtifactDescriptor(
            reference=SourceReference("inst/PROJ:PROJ-140", SourceType.JIRA),
            revision="r1",
            kind=ArtifactKind.TEST_CASE,
            external_keys=("PROJ-140",),
            title="PROJ-140",
        )
    )
    index.upsert(
        ArtifactDescriptor(
            reference=SourceReference("inst/PROJ:PROJ-123", SourceType.JIRA),
            revision="r1",
            kind=ArtifactKind.STORY,
            external_keys=("PROJ-123",),
            title="PROJ-123",
        )
    )
    first_mapping = _jira_link_mapping(_settings_with_link_type("Custom Test"))
    first = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: ("prj_orders",),
        extractors={
            SourceType.JIRA: JiraExplicitLinkExtractor(first_mapping)
        },
        raw_from_document=lambda source: decode_provider_links_raw(
            source.metadata.extra
        ),
        mapping_fingerprint=first_mapping.fingerprint(),
    )
    payload = {
        "v": 1,
        "issue_key": "PROJ-140",
        "links": [
            {
                "field": "issuelinks",
                "type_name": "Custom Test",
                "direction": "outward",
                "other_key": "PROJ-123",
            }
        ],
    }
    source = SourceDocument(
        SourceMetadata(
            reference=SourceReference("inst/PROJ:PROJ-140", SourceType.JIRA),
            title="PROJ-140",
            provider="jira",
            content_format="markdown",
            extra={PROVIDER_LINKS_EXTRA_KEY: encode_provider_links(payload)},
        ),
        "# PROJ-140",
    )
    first.execute(source, revision="r1")
    assert first.needs_record(source, revision="r1") is False

    second_mapping = _jira_link_mapping(_settings_with_link_type("Other Custom"))
    second = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: ("prj_orders",),
        extractors={
            SourceType.JIRA: JiraExplicitLinkExtractor(second_mapping)
        },
        raw_from_document=first._raw_from_document,
        mapping_fingerprint=second_mapping.fingerprint(),
    )
    assert first_mapping.fingerprint() != second_mapping.fingerprint()
    assert second.needs_record(source, revision="r1") is True
