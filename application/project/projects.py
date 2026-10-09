"""Create, list and fetch projects within one workspace."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from application.project.coverage import context_coverage
from domain.project.errors import ProjectNotFoundError
from domain.project.models import (
    AssociationState,
    ContextAssociationCoverage,
    Project,
    ProjectComponent,
    SourceAssociation,
    new_project_id,
)
from domain.project.ports import (
    ContextVocabulary,
    ProjectTransaction,
    ProjectUnitOfWork,
)


@dataclass(frozen=True, slots=True)
class CreateProjectRequest:
    name: str
    slug: str


class CreateProject:
    """Create a project with a Kernector-generated ``project_id``."""

    def __init__(
        self,
        *,
        store: ProjectUnitOfWork,
        new_id: Callable[[], str] = new_project_id,
    ) -> None:
        self._store = store
        self._new_id = new_id

    def execute(self, request: CreateProjectRequest) -> Project:
        """Raises ``ProjectSlugTakenError`` when the slug is in use."""
        name = request.name.strip() if isinstance(request.name, str) else request.name
        project = Project(self._new_id(), name, request.slug, 1)
        with self._store.transaction() as tx:
            tx.projects.add(project)
        return project


@dataclass(frozen=True, slots=True)
class ProjectOverview:
    """A project with its confirmed associations."""

    project: Project
    confirmed_associations: tuple[SourceAssociation, ...]


class ListProjects:
    """List the workspace's projects with their confirmed associations."""

    def __init__(self, *, store: ProjectUnitOfWork) -> None:
        self._store = store

    def execute(self) -> tuple[ProjectOverview, ...]:
        with self._store.read() as tx:
            return tuple(
                ProjectOverview(project, confirmed_associations(tx, project.project_id))
                for project in tx.projects.list()
            )


@dataclass(frozen=True, slots=True)
class ProjectDetail:
    """A project with every association, component and its context coverage."""

    project: Project
    associations: tuple[SourceAssociation, ...]
    components: tuple[ProjectComponent, ...]
    context_coverage: tuple[ContextAssociationCoverage, ...] = ()


class GetProject:
    """Fetch one project with its associations, components and coverage."""

    def __init__(
        self,
        *,
        store: ProjectUnitOfWork,
        vocabulary: ContextVocabulary | None = None,
    ) -> None:
        self._store = store
        self._vocabulary = vocabulary

    def execute(self, project_id: str) -> ProjectDetail:
        """Raises ``ProjectNotFoundError`` for an unknown ``project_id``."""
        with self._store.read() as tx:
            project = require_project(tx, project_id)
            associations = tx.associations.for_project(project_id)
            return ProjectDetail(
                project,
                associations,
                tx.components.for_project(project_id),
                context_coverage(associations, self._vocabulary),
            )


def require_project(tx: ProjectTransaction, project_id: str) -> Project:
    project = tx.projects.get(project_id)
    if project is None:
        raise ProjectNotFoundError("project not found")
    return project


def confirmed_associations(
    tx: ProjectTransaction, project_id: str
) -> tuple[SourceAssociation, ...]:
    return tuple(
        association
        for association in tx.associations.for_project(project_id)
        if association.state is AssociationState.CONFIRMED
    )
