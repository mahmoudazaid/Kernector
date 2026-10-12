"""Suggest associations from authoritative provider-declared evidence only.

A suggestion is made only when evidence links a scope that is already
confirmed in a project to another scope. There is no name or similarity
matching. Suggestions never override an existing association in any state.
"""

from __future__ import annotations

from domain.knowledge import SourceReference
from domain.project.models import AssociationState, SourceAssociation, SourceScope
from domain.project.ports import AssociationEvidenceSource, ProjectUnitOfWork

SUGGESTION_ACTOR = "evidence"


class SuggestAssociations:
    """Record ``suggested`` associations cited by authoritative evidence."""

    def __init__(
        self, *, store: ProjectUnitOfWork, evidence: AssociationEvidenceSource
    ) -> None:
        self._store = store
        self._evidence = evidence

    def execute(self) -> tuple[SourceAssociation, ...]:
        """Return the suggestions created by this run."""
        items = tuple(self._evidence.evidence())
        created: list[SourceAssociation] = []
        with self._store.transaction() as tx:
            cited: dict[tuple[str, SourceScope], list[SourceReference]] = {}
            for item in items:
                for association in tx.associations.for_scope(item.source_scope):
                    if association.state is not AssociationState.CONFIRMED:
                        continue
                    references = cited.setdefault(
                        (association.project_id, item.target_scope), []
                    )
                    if item.reference not in references:
                        references.append(item.reference)
            for (project_id, scope), references in cited.items():
                if tx.associations.get(project_id, scope) is not None:
                    continue
                suggestion = SourceAssociation(
                    project_id=project_id,
                    scope=scope,
                    roles=(),
                    state=AssociationState.SUGGESTED,
                    evidence=tuple(references),
                    created_by=SUGGESTION_ACTOR,
                    version=1,
                )
                created.append(tx.associations.add(suggestion))
        return tuple(created)
