"""Associate, confirm and remove source associations.

Every transition into ``confirmed`` checks shared scopes inside the same
transaction as the write, so a concurrently confirmed project cannot be
bypassed by a stale acknowledgement.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from application.project.projects import require_project
from domain.project.errors import (
    AssociationExistsError,
    AssociationNotFoundError,
    ProjectInputError,
    ProjectRecordVersionConflictError,
    SharedScopeConfirmationRequiredError,
)
from domain.project.models import (
    AssociationState,
    SourceAssociation,
    SourceScope,
    can_transition,
)
from domain.project.ports import (
    ContextVocabulary,
    ProjectTransaction,
    ProjectUnitOfWork,
)


@dataclass(frozen=True, slots=True)
class AssociateSourceRequest:
    project_id: str
    scope: SourceScope
    roles: tuple[str, ...]
    created_by: str
    acknowledged_shared_with: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ConfirmAssociationRequest:
    project_id: str
    scope: SourceScope
    expected_version: int
    roles: tuple[str, ...] | None = None
    acknowledged_shared_with: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class RemoveAssociationRequest:
    project_id: str
    scope: SourceScope
    expected_version: int


def require_shared_acknowledgement(
    tx: ProjectTransaction,
    project_id: str,
    scope: SourceScope,
    acknowledged: frozenset[str],
) -> None:
    """Reject confirming a scope already confirmed in unacknowledged projects."""
    others = {
        association.project_id
        for association in tx.associations.for_scope(scope)
        if association.state is AssociationState.CONFIRMED
        and association.project_id != project_id
    }
    if others and not others <= acknowledged:
        raise SharedScopeConfirmationRequiredError(tuple(others))


def require_known_roles(
    roles: tuple[str, ...], vocabulary: ContextVocabulary | None
) -> None:
    """Reject roles outside the registered vocabulary (any role without one)."""
    known = frozenset(() if vocabulary is None else vocabulary.contexts)
    if vocabulary is None and roles:
        raise ProjectInputError("roles need a registered context vocabulary")
    if not set(roles) <= known:
        raise ProjectInputError("roles must be registered contexts")


class AssociateSource:
    """Explicitly associate a scope with a project as ``confirmed``."""

    def __init__(
        self,
        *,
        store: ProjectUnitOfWork,
        vocabulary: ContextVocabulary | None = None,
    ) -> None:
        self._store = store
        self._vocabulary = vocabulary

    def execute(self, request: AssociateSourceRequest) -> SourceAssociation:
        """Raises:
        ProjectNotFoundError, AssociationExistsError,
        SharedScopeConfirmationRequiredError, ProjectInputError.
        """
        association = SourceAssociation(
            project_id=request.project_id,
            scope=request.scope,
            roles=request.roles,
            state=AssociationState.CONFIRMED,
            evidence=(),
            created_by=request.created_by,
            version=1,
        )
        with self._store.transaction() as tx:
            require_project(tx, request.project_id)
            if tx.associations.get(request.project_id, request.scope) is not None:
                raise AssociationExistsError(
                    "the project already has an association for this scope"
                )
            require_shared_acknowledgement(
                tx,
                request.project_id,
                request.scope,
                request.acknowledged_shared_with,
            )
            require_known_roles(association.roles, self._vocabulary)
            tx.associations.add(association)
        return association


class ConfirmAssociation:
    """Confirm a suggested or rejected association with compare-and-swap."""

    def __init__(
        self,
        *,
        store: ProjectUnitOfWork,
        vocabulary: ContextVocabulary | None = None,
    ) -> None:
        self._store = store
        self._vocabulary = vocabulary

    def execute(self, request: ConfirmAssociationRequest) -> SourceAssociation:
        """Raises:
        ProjectNotFoundError, AssociationNotFoundError,
        ProjectRecordVersionConflictError, SharedScopeConfirmationRequiredError,
        ProjectInputError.
        """
        with self._store.transaction() as tx:
            require_project(tx, request.project_id)
            current = tx.associations.get(request.project_id, request.scope)
            if current is None:
                raise AssociationNotFoundError(
                    "no association for this project and scope"
                )
            if current.version != request.expected_version:
                raise ProjectRecordVersionConflictError(
                    f"expected version {request.expected_version}, "
                    f"stored version is {current.version}"
                )
            if not can_transition(current.state, AssociationState.CONFIRMED):
                raise ProjectInputError("association is already confirmed")
            require_shared_acknowledgement(
                tx,
                request.project_id,
                request.scope,
                request.acknowledged_shared_with,
            )
            updated = replace(
                current,
                state=AssociationState.CONFIRMED,
                roles=current.roles if request.roles is None else request.roles,
            )
            require_known_roles(updated.roles, self._vocabulary)
            return tx.associations.update(
                updated, expected_version=request.expected_version
            )


class RemoveAssociation:
    """Remove an association; its evidence leaves project reads immediately."""

    def __init__(self, *, store: ProjectUnitOfWork) -> None:
        self._store = store

    def execute(self, request: RemoveAssociationRequest) -> None:
        """Raises:
        ProjectNotFoundError, AssociationNotFoundError,
        ProjectRecordVersionConflictError.
        """
        with self._store.transaction() as tx:
            require_project(tx, request.project_id)
            tx.associations.delete(
                request.project_id,
                request.scope,
                expected_version=request.expected_version,
            )
