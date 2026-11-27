"""Build artifact index, extractors, lookup, and sync hooks (#373)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from application.artifact.lookup import LookupArtifacts
from application.artifact.sync import SyncArtifactDescriptors
from application.errors import ConfigurationError
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


def _require_catalog_sql_path(settings: Settings) -> Path:
    path = settings.document_catalog.sql_path
    if path is None:
        raise ConfigurationError(
            "DOCUMENT_CATALOG_SQL_PATH is blank; unset it to use the "
            "data/catalog/catalog.sqlite default"
        )
    return path


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
    from composition.container import _require_workspace_id

    return SqlArtifactIndex(
        _require_catalog_sql_path(settings),
        _require_workspace_id(settings),
    )


def build_artifact_extractor() -> CompositeArtifactDescriptorExtractor:
    return CompositeArtifactDescriptorExtractor(
        (
            JiraArtifactDescriptorExtractor(),
            GitHubArtifactDescriptorExtractor(),
            DocumentArtifactDescriptorExtractor(),
        )
    )


def build_lookup_artifacts(settings: Settings) -> LookupArtifacts:
    from composition.container import _require_workspace_id

    catalog = SqlDocumentCatalog(
        _require_catalog_sql_path(settings),
        _require_workspace_id(settings),
    )
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
    from composition.relationship.container import build_relationship_store

    store = build_relationship_store(settings)
    for reference in references:
        index.remove(reference)
        store.clear_record_watermark(reference)


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

    from composition.relationship.container import build_relationship_recorders

    return SyncArtifactDescriptors(
        build_artifact_extractor(),
        build_artifact_index(settings),
        classify=classify,
        rules=rules,
        facts_for=facts_for,
        component_ids_for=component_ids_for,
        relationships=build_relationship_recorders(settings),
    )
