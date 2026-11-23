"""Build artifact index, extractors, lookup, and sync hooks (#373)."""

from __future__ import annotations

from pathlib import Path

from application.artifact.lookup import LookupArtifacts
from application.artifact.sync import SyncArtifactDescriptors
from domain.artifact.models import ArtifactDescriptor
from domain.artifact.ports import ArtifactDescriptorExtractor
from domain.knowledge import SourceDocument
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
from composition.project.container import build_resolve_projects_for_source


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


def build_artifact_sync(settings: Settings) -> SyncArtifactDescriptors:
    return SyncArtifactDescriptors(
        build_artifact_extractor(),
        build_artifact_index(settings),
    )
