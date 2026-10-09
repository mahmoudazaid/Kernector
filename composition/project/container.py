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
from application.project.components import ResolveComponentsForSource
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


def declared_scope_kinds(
    resolvers: Mapping[str, SourceScopeResolver],
) -> frozenset[str]:
    """Union of the scope kinds connectors accept in an association."""
    return frozenset().union(*(resolver.scope_kinds for resolver in resolvers.values()))


def component_forming_kinds(
    resolvers: Mapping[str, SourceScopeResolver],
) -> frozenset[str]:
    """Union of the scope kinds connectors declare component-forming."""
    return frozenset().union(
        *(resolver.component_forming_scope_kinds for resolver in resolvers.values())
    )


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
    resolvers = build_scope_resolvers()
    scope_kinds = declared_scope_kinds(resolvers)
    kinds = component_forming_kinds(resolvers)
    return ProjectUseCases(
        create=CreateProject(store=store),
        list=ListProjects(store=store),
        get=GetProject(store=store, vocabulary=vocabulary),
        associate=AssociateSource(
            store=store,
            vocabulary=vocabulary,
            scope_kinds=scope_kinds,
            component_forming_kinds=kinds,
        ),
        confirm=ConfirmAssociation(
            store=store,
            vocabulary=vocabulary,
            scope_kinds=scope_kinds,
            component_forming_kinds=kinds,
        ),
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


def build_resolve_components_for_source(
    settings: Settings,
) -> ResolveComponentsForSource:
    """Wire document-to-component resolution over the catalog."""
    from composition.container import build_document_catalog

    return ResolveComponentsForSource(
        store=build_project_store(settings),
        catalog=build_document_catalog(settings),
        resolvers=build_scope_resolvers(),
    )
