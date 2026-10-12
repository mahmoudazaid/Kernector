"""Structural context coverage: which registered contexts a project declares.

This report never looks at sync state, freshness or evidence; ``associated``
only means a confirmed association lists the context as a role.
"""

from __future__ import annotations

from collections.abc import Iterable

from domain.project.errors import ProjectNotFoundError
from domain.project.models import (
    AssociationState,
    ContextAssociationCoverage,
    ContextAssociationStatus,
    SourceAssociation,
)
from domain.project.ports import ContextVocabulary, ProjectUnitOfWork


def context_coverage(
    associations: Iterable[SourceAssociation],
    vocabulary: ContextVocabulary | None,
) -> tuple[ContextAssociationCoverage, ...]:
    """Return one entry per registered context, in vocabulary order."""
    if vocabulary is None:
        return ()
    confirmed = sorted(
        (a for a in associations if a.state is AssociationState.CONFIRMED),
        key=lambda a: (a.scope.connector_id, a.scope.scope_kind, a.scope.scope_value),
    )
    report: list[ContextAssociationCoverage] = []
    for context in vocabulary.contexts:
        scopes = tuple(a.scope for a in confirmed if context in a.roles)
        status = (
            ContextAssociationStatus.ASSOCIATED
            if scopes
            else ContextAssociationStatus.NOT_ASSOCIATED
        )
        report.append(ContextAssociationCoverage(context, status, scopes))
    return tuple(report)


class ProjectContextCoverage:
    """Report ``associated`` / ``not_associated`` for every registered context."""

    def __init__(
        self, *, store: ProjectUnitOfWork, vocabulary: ContextVocabulary | None
    ) -> None:
        self._store = store
        self._vocabulary = vocabulary

    def execute(self, project_id: str) -> tuple[ContextAssociationCoverage, ...]:
        """Raises ``ProjectNotFoundError`` for an unknown ``project_id``."""
        with self._store.read() as tx:
            if tx.projects.get(project_id) is None:
                raise ProjectNotFoundError("project not found")
            return context_coverage(
                tx.associations.for_project(project_id), self._vocabulary
            )
