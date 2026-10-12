"""Resolve catalog documents to projects through confirmed associations."""

from __future__ import annotations

from collections.abc import Mapping

from domain.knowledge import CatalogDocument, SourceReference
from domain.ports import DocumentCatalog
from domain.project.models import AssociationState, SourceScope
from domain.project.ports import ProjectUnitOfWork, SourceScopeResolver


def document_scopes(
    document: CatalogDocument, resolvers: Mapping[str, SourceScopeResolver]
) -> tuple[SourceScope, ...]:
    """Return the document's scopes; ``()`` without connector or resolver."""
    if document.connector_id is None:
        return ()
    resolver = resolvers.get(str(document.reference.source_type))
    if resolver is None:
        return ()
    return tuple(
        scope
        for scope in resolver.scopes_for(document)
        if scope.connector_id == document.connector_id
    )


class ResolveProjectsForSource:
    """Map a catalog document to every project with a confirmed association."""

    def __init__(
        self,
        *,
        store: ProjectUnitOfWork,
        catalog: DocumentCatalog,
        resolvers: Mapping[str, SourceScopeResolver],
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._resolvers = resolvers

    def execute(self, reference: SourceReference) -> tuple[str, ...]:
        """Return sorted ``project_id`` values; ``()`` when unassociated."""
        document = self._catalog.get(reference)
        if document is None:
            return ()
        scopes = document_scopes(document, self._resolvers)
        if not scopes:
            return ()
        with self._store.read() as tx:
            project_ids = {
                association.project_id
                for scope in scopes
                for association in tx.associations.for_scope(scope)
                if association.state is AssociationState.CONFIRMED
            }
        return tuple(sorted(project_ids))
