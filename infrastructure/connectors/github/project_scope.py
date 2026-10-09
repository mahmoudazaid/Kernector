"""GitHub source scope resolution for project associations (#372).

Repository files have ``source_id`` ``{owner}/{repo}:{path}``. ProjectV2 issue
documents (``issue:{node_id}``) carry no repository, so they have no scope.
"""

from __future__ import annotations

import re

from domain.knowledge import CatalogDocument, SourceType
from domain.project.models import SourceScope

REPO_SCOPE_KIND = "repo"
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def _split(document: CatalogDocument) -> tuple[str, str] | None:
    if document.connector_id is None:
        return None
    if document.reference.source_type != SourceType.GITHUB:
        return None
    repository, separator, path = document.reference.source_id.partition(":")
    if not separator or not path or not _REPOSITORY.fullmatch(repository):
        return None
    return repository, path


class GitHubSourceScopeResolver:
    """Map repository files to ``repo={owner}/{repo}`` plus their path."""

    @property
    def scope_kinds(self) -> frozenset[str]:
        return frozenset({REPO_SCOPE_KIND})

    @property
    def component_forming_scope_kinds(self) -> frozenset[str]:
        return frozenset({REPO_SCOPE_KIND})

    def scopes_for(self, document: CatalogDocument) -> tuple[SourceScope, ...]:
        split = _split(document)
        if split is None or document.connector_id is None:
            return ()
        return (SourceScope(document.connector_id, REPO_SCOPE_KIND, split[0]),)

    def path_for(self, document: CatalogDocument) -> str | None:
        split = _split(document)
        return None if split is None else split[1]
