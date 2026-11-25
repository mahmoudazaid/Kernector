"""Build relationship store and use cases (#374)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from application.relationship.list import ListArtifactRelationships
from application.relationship.record import RecordExplicitRelationships
from domain.knowledge import SourceDocument, SourceType
from domain.project.errors import ProjectNotFoundError
from infrastructure.connectors.jira.link_extractor import (
    EXTRACTOR_ID,
    JiraExplicitLinkExtractor,
    JiraLinkTypeMapping,
    DEFAULT_TYPE_MAP,
    decode_provider_links_raw,
)
from infrastructure.config import Settings
from infrastructure.relationship.sql_store import SqlRelationshipStore
from composition.artifact.container import build_artifact_index
from composition.project.container import (
    build_project_use_cases,
    build_resolve_projects_for_source,
)

_INVERSE_NAMES_TARGET = (
    "packs.software_delivery.relationship.types:RELATION_INVERSE_NAMES"
)


def build_relationship_store(settings: Settings) -> SqlRelationshipStore:
    path = Path(settings.document_catalog.sql_path)
    return SqlRelationshipStore(path, settings.document_catalog.workspace_id)


def _jira_raw_from_document(source: SourceDocument) -> dict[str, object] | None:
    from infrastructure.connectors.jira.link_extractor import PROVIDER_LINKS_EXTRA_KEY

    if PROVIDER_LINKS_EXTRA_KEY not in source.metadata.extra:
        return None
    return decode_provider_links_raw(source.metadata.extra)


def _jira_link_mapping(settings: Settings) -> JiraLinkTypeMapping:
    """Build the link-type table, including the configured Xray link type."""
    mapping: dict[str, tuple[str, str]] = dict(DEFAULT_TYPE_MAP)
    link_type = settings.xray.link_type.strip()
    if link_type:
        mapping[link_type.casefold()] = ("tests", "subject")
    return JiraLinkTypeMapping(by_name=mapping)


def _load_inverse_names(settings: Settings) -> Mapping[str, str]:
    """Load pack inverse names only when the pack is enabled (lazy import)."""
    if "software-delivery" not in settings.domain_tools.enabled_packs:
        return {}
    import importlib

    module_name, _, attr = _INVERSE_NAMES_TARGET.partition(":")
    module = importlib.import_module(module_name)
    loaded = getattr(module, attr)
    return dict(loaded)


def build_record_explicit_relationships(
    settings: Settings,
) -> RecordExplicitRelationships:
    resolve = build_resolve_projects_for_source(settings)
    return RecordExplicitRelationships(
        build_relationship_store(settings),
        build_artifact_index(settings),
        project_ids_for=resolve.execute,
        extractors={
            SourceType.JIRA: JiraExplicitLinkExtractor(_jira_link_mapping(settings))
        },
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
        except ProjectNotFoundError:
            return False
        return True

    return ListArtifactRelationships(
        build_relationship_store(settings),
        build_artifact_index(settings),
        project_exists=project_exists,
        project_ids_for=resolve.execute,
        inverse_names=_load_inverse_names(settings),
    )
