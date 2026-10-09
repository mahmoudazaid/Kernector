"""Build workspace-bound project use cases from settings.

The project tables live in the catalog database. No ``AssociationEvidenceSource``
is wired: no production source supplies authoritative association evidence yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from application.errors import ConfigurationError
from application.project.associations import (
    AssociateSource,
    ConfirmAssociation,
    RemoveAssociation,
)
from application.project.coverage import ProjectContextCoverage
from application.project.projects import CreateProject, GetProject, ListProjects
from application.project.resolve import ResolveProjectsForSource
from composition.project.vocabulary import build_context_vocabulary
from domain.knowledge import SourceType
from domain.project.ports import SourceScopeResolver
from infrastructure.config import Settings
from infrastructure.connectors.github.project_scope import GitHubSourceScopeResolver
from infrastructure.connectors.jira.project_scope import JiraSourceScopeResolver
from infrastructure.project.sql_store import SqlProjectStore


@dataclass(frozen=True, slots=True)
class ProjectUseCases:
    """Use cases bound to one workspace's project store."""

    create: CreateProject
    list: ListProjects
    get: GetProject
    associate: AssociateSource
    confirm: ConfirmAssociation
    remove: RemoveAssociation
    coverage: ProjectContextCoverage


def build_scope_resolvers() -> Mapping[str, SourceScopeResolver]:
    """Return connector scope resolvers keyed by catalog ``source_type``."""
    return {
        str(SourceType.GITHUB): GitHubSourceScopeResolver(),
        str(SourceType.JIRA): JiraSourceScopeResolver(),
    }


def build_project_store(settings: Settings) -> SqlProjectStore:
    """Return the project store bound to ``DOCUMENT_CATALOG_WORKSPACE_ID``."""
    from composition.container import _require_workspace_id

    path = settings.document_catalog.sql_path
    if path is None:
        raise ConfigurationError(
            "DOCUMENT_CATALOG_SQL_PATH is blank; unset it to use the "
            "data/catalog/catalog.sqlite default"
        )
    return SqlProjectStore(path, _require_workspace_id(settings))


def build_project_use_cases(settings: Settings) -> ProjectUseCases:
    """Wire the project use cases for HTTP and MCP."""
    store = build_project_store(settings)
    vocabulary = build_context_vocabulary(settings)
    return ProjectUseCases(
        create=CreateProject(store=store),
        list=ListProjects(store=store),
        get=GetProject(store=store, vocabulary=vocabulary),
        associate=AssociateSource(store=store, vocabulary=vocabulary),
        confirm=ConfirmAssociation(store=store, vocabulary=vocabulary),
        remove=RemoveAssociation(store=store),
        coverage=ProjectContextCoverage(store=store, vocabulary=vocabulary),
    )


def build_resolve_projects_for_source(settings: Settings) -> ResolveProjectsForSource:
    """Wire document-to-project resolution over the catalog."""
    from composition.container import build_document_catalog

    return ResolveProjectsForSource(
        store=build_project_store(settings),
        catalog=build_document_catalog(settings),
        resolvers=build_scope_resolvers(),
    )
