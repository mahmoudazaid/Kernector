"""Jira source scope resolution for project associations (#372).

Catalogued issues have ``source_id`` ``{instance_id}/{project_key}:{issue_key}``
(see ``project_source_id_prefix``). The instance id may contain ``/``; the
project key and issue key never contain ``/`` or ``:``.
"""

from __future__ import annotations

import re

from domain.knowledge import CatalogDocument, SourceType
from domain.project.models import SourceScope

PROJECT_KEY_SCOPE_KIND = "project_key"
_PROJECT_KEY = re.compile(r"[A-Z][A-Z0-9_]{0,254}")
_ISSUE_NUMBER = re.compile(r"[0-9]+")


def _project_key(document: CatalogDocument) -> str | None:
    if document.reference.source_type != SourceType.JIRA:
        return None
    head, separator, issue_key = document.reference.source_id.rpartition(":")
    if not separator:
        return None
    instance_id, slash, project_key = head.rpartition("/")
    if not slash or not instance_id or not _PROJECT_KEY.fullmatch(project_key):
        return None
    prefix = f"{project_key}-"
    if not issue_key.startswith(prefix):
        return None
    if not _ISSUE_NUMBER.fullmatch(issue_key[len(prefix):]):
        return None
    return project_key


class JiraSourceScopeResolver:
    """Map issues to ``project_key={KEY}``; issues have no path."""

    @property
    def component_forming_scope_kinds(self) -> frozenset[str]:
        return frozenset()

    def scopes_for(self, document: CatalogDocument) -> tuple[SourceScope, ...]:
        if document.connector_id is None:
            return ()
        project_key = _project_key(document)
        if project_key is None:
            return ()
        return (SourceScope(document.connector_id, PROJECT_KEY_SCOPE_KIND, project_key),)

    def path_for(self, document: CatalogDocument) -> str | None:
        return None
