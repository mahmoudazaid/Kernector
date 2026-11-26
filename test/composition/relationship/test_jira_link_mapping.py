"""Configured Jira link-type mapping and mapping fingerprint (#374)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from composition.relationship.container import (
    _jira_link_mapping,
    build_record_explicit_relationships,
)
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
    encode_provider_links,
)


def _settings_with_link_type(link_type: str):
    settings = load_settings()
    return replace(settings, xray=replace(settings.xray, link_type=link_type))


class _FixedProjects:
    def execute(self, reference: SourceReference) -> tuple[str, ...]:
        del reference
        return ("prj_orders",)


def test_xray_link_type_relates_does_not_overwrite_default() -> None:
    mapping = _jira_link_mapping(_settings_with_link_type("Relates"))
    assert mapping.by_name["relates"] == ("relates_to", "subject")


def test_custom_xray_link_type_maps_to_tests() -> None:
    mapping = _jira_link_mapping(_settings_with_link_type("Verified By"))
    assert mapping.by_name["verified by"] == ("tests", "subject")


def test_container_mapping_fingerprint_change_triggers_needs_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "ws-a")
    monkeypatch.setattr(
        "composition.relationship.container.build_resolve_projects_for_source",
        lambda _settings: _FixedProjects(),
    )
    index = SqlArtifactIndex(tmp_path / "catalog.sqlite", "ws-a")
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
    first = build_record_explicit_relationships(
        _settings_with_link_type("Custom Test")
    )
    first.execute(source, revision="r1")
    assert first.needs_retry(source.reference, revision="r1") is False

    second = build_record_explicit_relationships(
        _settings_with_link_type("Other Custom")
    )
    assert first._mapping_fingerprint != second._mapping_fingerprint
    assert second.needs_retry(source.reference, revision="r1") is True
