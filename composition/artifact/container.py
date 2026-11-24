"""Build artifact index, extractors, lookup, and sync hooks (#373)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from application.artifact.lookup import LookupArtifacts
from application.artifact.sync import SyncArtifactDescriptors
from domain.artifact.models import ArtifactDescriptor
from domain.artifact.ports import ArtifactDescriptorExtractor
from domain.knowledge import SourceDocument, SourceReference
from domain.project.models import ComponentResolutionStatus
from infrastructure.artifact.sql_index import SqlArtifactIndex
from infrastructure.catalog.sql_catalog import SqlDocumentCatalog
from infrastructure.connectors.document_artifact_extractor import (
    DocumentArtifactDescriptorExtractor,
)
from infrastructure.connectors.github.artifact_extractor import (
    GitHubArtifactDescriptorExtractor,
)
from infrastructure.connectors.jira.artifact_extractor import (
    JiraArtifactDescriptorExtractor,
)
from infrastructure.config import Settings
from composition.project.container import (
    build_resolve_components_for_source,
    build_resolve_projects_for_source,
)


class CompositeArtifactDescriptorExtractor:
    """Try connector-specific extractors in order; first hit wins."""

    def __init__(self, extractors: tuple[ArtifactDescriptorExtractor, ...]) -> None:
        self._extractors = extractors

    def describe(self, document: SourceDocument) -> ArtifactDescriptor | None:
        for extractor in self._extractors:
            descriptor = extractor.describe(document)
            if descriptor is not None:
                return descriptor
        return None


def build_artifact_index(settings: Settings) -> SqlArtifactIndex:
    path = Path(settings.document_catalog.sql_path)
    return SqlArtifactIndex(path, settings.document_catalog.workspace_id)


def build_artifact_extractor() -> CompositeArtifactDescriptorExtractor:
    return CompositeArtifactDescriptorExtractor(
        (
            JiraArtifactDescriptorExtractor(),
            GitHubArtifactDescriptorExtractor(),
            DocumentArtifactDescriptorExtractor(),
        )
    )


def build_lookup_artifacts(settings: Settings) -> LookupArtifacts:
    path = Path(settings.document_catalog.sql_path)
    workspace_id = settings.document_catalog.workspace_id
    catalog = SqlDocumentCatalog(path, workspace_id)
    resolve = build_resolve_projects_for_source(settings)
    return LookupArtifacts(
        build_artifact_index(settings),
        catalog,
        project_ids_for=resolve.execute,
    )


def remove_artifact_descriptors(
    settings: Settings, references: Sequence[SourceReference]
) -> None:
    """Drop descriptors for purged catalog sources."""
    if not references:
        return
    index = build_artifact_index(settings)
    for reference in references:
        index.remove(reference)


def build_artifact_sync(settings: Settings) -> SyncArtifactDescriptors:
    resolve_components = build_resolve_components_for_source(settings)

    def component_ids_for(reference: SourceReference) -> tuple[str, ...]:
        ids: list[str] = []
        for resolution in resolve_components.execute(reference):
            if resolution.status is ComponentResolutionStatus.RESOLVED:
                ids.extend(resolution.component_ids)
        return tuple(ids)

    classify = None
    rules: tuple = ()
    facts_for = None
    if "software-delivery" in settings.domain_tools.enabled_packs:
        from application.artifact.classify import classify_contexts
        from infrastructure.artifact.structural_facts import structural_facts_for
        from packs.software_delivery.project.classification_rules import (
            SOFTWARE_DELIVERY_CONTEXT_RULES,
        )

        classify = classify_contexts
        rules = SOFTWARE_DELIVERY_CONTEXT_RULES
        facts_for = structural_facts_for

    return SyncArtifactDescriptors(
        build_artifact_extractor(),
        build_artifact_index(settings),
        classify=classify,
        rules=rules,
        facts_for=facts_for,
        component_ids_for=component_ids_for,
    )
