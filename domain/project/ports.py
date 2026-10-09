"""Ports for project persistence, scope resolution and evidence.

Repositories are workspace-bound at construction and reached only through a
:class:`ProjectUnitOfWork` so multi-record operations commit or roll back
together.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from domain.knowledge import CatalogDocument
from domain.project.models import (
    AssociationEvidence,
    Project,
    ProjectComponent,
    SourceAssociation,
    SourceScope,
)


class ProjectRepository(Protocol):
    def add(self, project: Project) -> None:
        """Insert ``project``.

        Raises:
            ProjectSlugTakenError: The slug is used by another project.
        """
        ...

    def get(self, project_id: str) -> Project | None: ...

    def list(self) -> tuple[Project, ...]: ...


class SourceAssociationRepository(Protocol):
    def add(self, association: SourceAssociation) -> SourceAssociation:
        """Insert ``association`` and return it as stored.

        Versions are never reused for the same project and scope: after a
        removal the stored version continues past the removed one.

        Raises:
            AssociationExistsError: The project already has this scope.
        """
        ...

    def get(self, project_id: str, scope: SourceScope) -> SourceAssociation | None: ...

    def update(
        self, association: SourceAssociation, *, expected_version: int
    ) -> SourceAssociation:
        """Store ``association`` at ``expected_version + 1`` and return it.

        Raises:
            AssociationNotFoundError: No association for this project and scope.
            ProjectRecordVersionConflictError: The stored version differs.
        """
        ...

    def delete(
        self, project_id: str, scope: SourceScope, *, expected_version: int
    ) -> None:
        """Delete one association with compare-and-swap.

        Raises:
            AssociationNotFoundError: No association for this project and scope.
            ProjectRecordVersionConflictError: The stored version differs.
        """
        ...

    def for_project(self, project_id: str) -> tuple[SourceAssociation, ...]: ...

    def for_scope(self, scope: SourceScope) -> tuple[SourceAssociation, ...]: ...


class ProjectComponentRepository(Protocol):
    def add(self, component: ProjectComponent) -> None:
        """Insert ``component`` and its members.

        Raises:
            AssociationExistsError: A member already exists in the project.
        """
        ...

    def get(self, project_id: str, component_id: str) -> ProjectComponent | None: ...

    def update(
        self, component: ProjectComponent, *, expected_version: int
    ) -> ProjectComponent:
        """Replace name and members at ``expected_version + 1``.

        Raises:
            ComponentNotFoundError: No such component in the project.
            ProjectRecordVersionConflictError: The stored version differs.
            AssociationExistsError: A member already exists in another component.
        """
        ...

    def delete(
        self, project_id: str, component_id: str, *, expected_version: int
    ) -> None:
        """Delete a component and its members with compare-and-swap."""
        ...

    def for_project(self, project_id: str) -> tuple[ProjectComponent, ...]: ...


class ProjectTransaction(Protocol):
    """Repositories bound to one transaction."""

    @property
    def projects(self) -> ProjectRepository: ...

    @property
    def associations(self) -> SourceAssociationRepository: ...

    @property
    def components(self) -> ProjectComponentRepository: ...


class ProjectUnitOfWork(Protocol):
    def transaction(self) -> AbstractContextManager[ProjectTransaction]:
        """Open a write transaction; commit on clean exit, roll back on error.

        Writers are serialized, so checks made inside the transaction still
        hold when it commits.
        """
        ...

    def read(self) -> AbstractContextManager[ProjectTransaction]:
        """Open a consistent read-only snapshot."""
        ...


class SourceScopeResolver(Protocol):
    """Connector-owned mapping from a catalog document to its scope."""

    @property
    def scope_kinds(self) -> frozenset[str]:
        """Scope kinds this connector accepts in an association."""
        ...

    @property
    def component_forming_scope_kinds(self) -> frozenset[str]: ...

    def scopes_for(self, document: CatalogDocument) -> tuple[SourceScope, ...]:
        """Return the document's scopes, or ``()`` for an unsupported identity."""
        ...

    def path_for(self, document: CatalogDocument) -> str | None:
        """Return the document's path within its scope, or ``None``."""
        ...


class ContextVocabulary(Protocol):
    """Context tokens registered by enabled packs."""

    @property
    def contexts(self) -> tuple[str, ...]: ...


class AssociationEvidenceSource(Protocol):
    """Provider-declared links between scopes (Jira remote links, for example)."""

    def evidence(self) -> Sequence[AssociationEvidence]: ...
