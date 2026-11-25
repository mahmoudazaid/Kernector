"""Build relationship store and use cases (#374)."""

from __future__ import annotations

from pathlib import Path

from application.relationship.list import ListArtifactRelationships
from application.relationship.record import RecordExplicitRelationships
from domain.knowledge import SourceDocument, SourceType
from infrastructure.connectors.jira.link_extractor import (
    EXTRACTOR_ID,
    JiraExplicitLinkExtractor,
    decode_provider_links_raw,
)
from infrastructure.config import Settings
from infrastructure.relationship.sql_store import SqlRelationshipStore
from composition.artifact.container import build_artifact_index
from composition.project.container import (
    build_project_use_cases,
    build_resolve_projects_for_source,
)


def build_relationship_store(settings: Settings) -> SqlRelationshipStore:
    path = Path(settings.document_catalog.sql_path)
    return SqlRelationshipStore(path, settings.document_catalog.workspace_id)


def _jira_raw_from_document(source: SourceDocument) -> dict[str, object] | None:
    from infrastructure.connectors.jira.link_extractor import PROVIDER_LINKS_EXTRA_KEY

    if PROVIDER_LINKS_EXTRA_KEY not in source.metadata.extra:
        return None
    return decode_provider_links_raw(source.metadata.extra)


def build_record_explicit_relationships(
    settings: Settings,
) -> RecordExplicitRelationships:
    resolve = build_resolve_projects_for_source(settings)
    return RecordExplicitRelationships(
        build_relationship_store(settings),
        build_artifact_index(settings),
        project_ids_for=resolve.execute,
        extractors={SourceType.JIRA: JiraExplicitLinkExtractor()},
        raw_from_document=_jira_raw_from_document,
        extractor_id=EXTRACTOR_ID,
    )


def build_list_artifact_relationships(
    settings: Settings,
) -> ListArtifactRelationships:
    projects = build_project_use_cases(settings)
    resolve = build_resolve_projects_for_source(settings)

    def project_exists(project_id: str) -> bool:
        try:
            projects.get.execute(project_id)
        except Exception:
            return False
        return True

    return ListArtifactRelationships(
        build_relationship_store(settings),
        build_artifact_index(settings),
        project_exists=project_exists,
        project_ids_for=resolve.execute,
    )
