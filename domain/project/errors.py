"""Project Intelligence errors.

Each subclass gets its own Problem Details branch; the generic
``DomainValidationError`` mapping is an operational failure.
"""

from __future__ import annotations

from domain.errors import DomainValidationError


class ProjectError(DomainValidationError):
    """Base for project, association and component failures."""


class ProjectInputError(ProjectError):
    """A project, scope, role, path or component request is invalid."""


class ProjectNotFoundError(ProjectError):
    """No project with this id exists in the workspace."""


class AssociationNotFoundError(ProjectError):
    """The project has no association for this scope."""


class ComponentNotFoundError(ProjectError):
    """No component with this id exists in the project."""


class ProjectRecordVersionConflictError(ProjectError):
    """``expected_version`` does not match the stored record."""


class AssociationExistsError(ProjectError):
    """The project already has this association or component member."""


class ProjectSlugTakenError(ProjectError):
    """Another project in the workspace already uses this slug."""


class SharedScopeConfirmationRequiredError(ProjectError):
    """The scope is confirmed in other projects the caller did not acknowledge."""

    def __init__(self, project_ids: tuple[str, ...]) -> None:
        self.project_ids = tuple(sorted(project_ids))
        super().__init__(
            "scope is already confirmed in other projects; acknowledge them to share it"
        )
