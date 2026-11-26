"""Trusted project access policy seam (#377 / #446).

Authorization consumers receive a ``ProjectAccessCaller`` built from
server-side session/MCP resolution (#447). Request-body principal, workspace,
role, or project scope must never be trusted as the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from domain.auth.principal import Principal


@dataclass(frozen=True, slots=True)
class ProjectAccessCaller:
    """Trusted principal plus server-bound workspace context."""

    principal: Principal
    workspace_id: str


class ProjectAccessPolicy(Protocol):
    """Shared authorization seam for project reads (#377 / #446)."""

    def can_read(self, caller: ProjectAccessCaller, project_id: str) -> bool:
        """Return whether *caller* may read *project_id*."""
        ...

    def readable_projects(self, caller: ProjectAccessCaller) -> tuple[str, ...]:
        """Return project ids *caller* may read in the bound workspace."""
        ...
