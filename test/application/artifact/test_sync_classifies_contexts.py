"""SyncArtifactDescriptors classifies contexts when classify/facts_for wired."""

from __future__ import annotations

from dataclasses import replace

from application.artifact.classify import classify_contexts
from application.artifact.sync import SyncArtifactDescriptors
from composition.artifact.container import build_artifact_sync
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.artifact.structural_facts import structural_facts_for
from infrastructure.config import DomainToolSettings, load_settings
from packs.software_delivery.project.classification_rules import (
    SOFTWARE_DELIVERY_CONTEXT_RULES,
)


class _Extractor:
    def describe(self, document: SourceDocument) -> ArtifactDescriptor | None:
        return ArtifactDescriptor(
            reference=document.reference,
            revision="from-extractor",
            kind=ArtifactKind.STORY,
            external_keys=("PROJ-1",),
            title=document.metadata.title,
        )


class _Index:
    def __init__(self) -> None:
        self.descriptors: dict[tuple[str, str], ArtifactDescriptor] = {}

    def upsert(self, descriptor: ArtifactDescriptor) -> None:
        key = (descriptor.reference.source_type, descriptor.reference.source_id)
        self.descriptors[key] = descriptor

    def remove(self, reference: SourceReference) -> None:
        self.descriptors.pop((reference.source_type, reference.source_id), None)

    def get(self, reference: SourceReference) -> ArtifactDescriptor | None:
        return self.descriptors.get((reference.source_type, reference.source_id))

    def find_by_key(self, keys: tuple[str, ...]) -> tuple[ArtifactDescriptor, ...]:
        return ()

    def list_for_scope(
        self, *, source_type: str | None = None
    ) -> tuple[ArtifactDescriptor, ...]:
        return ()


def test_jira_story_gets_business_context() -> None:
    source = SourceDocument(
        SourceMetadata(
            SourceReference("cloud/PROJ:PROJ-1", SourceType.JIRA),
            title="Login flow",
            extra={
                "jira_issue_type": "Story",
                "jira_issue_key": "PROJ-1",
                "jira_updated_at": "r1",
            },
        ),
        "As a user I can log in",
    )
    index = _Index()
    sync = SyncArtifactDescriptors(
        _Extractor(),
        index,
        classify=classify_contexts,
        rules=SOFTWARE_DELIVERY_CONTEXT_RULES,
        facts_for=structural_facts_for,
        component_ids_for=lambda _ref: ("cmp_auth",),
    )

    sync.on_ready(source, revision="r1")

    stored = index.get(source.reference)
    assert stored is not None
    assert {item.context for item in stored.contexts} == {"business"}
    assert stored.component_ids == ("cmp_auth",)


def test_build_artifact_sync_skips_pack_rules_when_pack_disabled(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "ws_test")
    settings = replace(
        load_settings(),
        domain_tools=DomainToolSettings(enabled_packs=()),
    )

    sync = build_artifact_sync(settings)

    assert sync._classify is None
    assert sync._rules == ()
    assert sync._facts_for is None


def test_build_artifact_sync_wires_pack_rules_when_enabled(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "ws_test")
    settings = replace(
        load_settings(),
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )

    sync = build_artifact_sync(settings)

    assert sync._classify is classify_contexts
    assert sync._rules == SOFTWARE_DELIVERY_CONTEXT_RULES
    assert sync._facts_for is structural_facts_for
