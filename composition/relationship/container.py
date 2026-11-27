"""Build relationship store and use cases (#374, #375)."""

from __future__ import annotations

from collections.abc import Mapping

from application.artifact.fanout_recorder import FanOutRelationshipRecorder
from application.relationship.list import ListArtifactRelationships
from application.relationship.match import MatchProjectReferences
from application.relationship.record import RecordExplicitRelationships
from domain.knowledge import SourceDocument, SourceType
from domain.project.errors import ProjectNotFoundError
from domain.relationship.matching import MatchLimits
from infrastructure.catalog.sql_catalog import SqlDocumentCatalog
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

RULE_CATALOGUE_VERSION = "software_delivery.matchers.v1"
DEFAULT_MATCH_LIMITS = MatchLimits(
    max_content_bytes=1_048_576,
    max_mentions=100,
    max_catalogue_entries=10_000,
    max_compiled_pattern_size=65_536,
)

_INVERSE_NAMES_TARGET = (
    "packs.software_delivery.relationship.types:RELATION_INVERSE_NAMES"
)


def build_relationship_store(settings: Settings) -> SqlRelationshipStore:
    from composition.artifact.container import _require_catalog_sql_path
    from composition.container import _require_workspace_id

    return SqlRelationshipStore(
        _require_catalog_sql_path(settings),
        _require_workspace_id(settings),
    )


def _jira_raw_from_document(source: SourceDocument) -> dict[str, object] | None:
    from infrastructure.connectors.jira.link_extractor import PROVIDER_LINKS_EXTRA_KEY

    if PROVIDER_LINKS_EXTRA_KEY not in source.metadata.extra:
        return None
    return decode_provider_links_raw(source.metadata.extra)


def _jira_link_mapping(settings: Settings) -> JiraLinkTypeMapping:
    """Build the link-type table, including the configured Xray link type.

    Defaults win over ``XRAY_LINK_TYPE`` so a custom type cannot overwrite
    built-in meanings such as ``Relates`` or ``Blocks``.
    """
    mapping: dict[str, tuple[str, str]] = dict(DEFAULT_TYPE_MAP)
    link_type = settings.xray.link_type.strip()
    if link_type:
        mapping.setdefault(link_type.casefold(), ("tests", "subject"))
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
    mapping = _jira_link_mapping(settings)
    return RecordExplicitRelationships(
        build_relationship_store(settings),
        build_artifact_index(settings),
        project_ids_for=resolve.execute,
        extractors={SourceType.JIRA: JiraExplicitLinkExtractor(mapping)},
        raw_from_document=_jira_raw_from_document,
        extractor_id=EXTRACTOR_ID,
        mapping_fingerprint=mapping.fingerprint(),
    )


def build_match_project_references(settings: Settings) -> MatchProjectReferences:
    """Build deterministic MatchProjectReferences when the pack is enabled."""
    from packs.software_delivery.relationship.matchers import (
        ApiOperationMentionMatcher,
        KeyMentionDocMatcher,
        KeyMentionHeaderMatcher,
        KeyMentionTagMatcher,
    )

    from composition.artifact.container import _require_catalog_sql_path
    from composition.container import _require_workspace_id

    resolve = build_resolve_projects_for_source(settings)
    return MatchProjectReferences(
        build_relationship_store(settings),
        build_artifact_index(settings),
        SqlDocumentCatalog(
            _require_catalog_sql_path(settings),
            _require_workspace_id(settings),
        ),
        project_ids_for=resolve.execute,
        matchers=(
            KeyMentionTagMatcher(),
            KeyMentionHeaderMatcher(),
            KeyMentionDocMatcher(),
            ApiOperationMentionMatcher(),
        ),
        limits=DEFAULT_MATCH_LIMITS,
        rule_catalogue_version=RULE_CATALOGUE_VERSION,
    )


def build_relationship_recorders(settings: Settings) -> FanOutRelationshipRecorder:
    """Fan-out provider-declared and deterministic recorders (#374/#375)."""
    children: list = [build_record_explicit_relationships(settings)]
    if "software-delivery" in settings.domain_tools.enabled_packs:
        children.append(build_match_project_references(settings))
    return FanOutRelationshipRecorder(children)


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
