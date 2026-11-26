"""Membership-and-grant-backed ProjectAccessPolicy adapter (#446)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from domain.auth.ports import MembershipStore, ProjectGrantStore
from domain.project.access import ProjectAccessCaller, ProjectAccessPolicy
from domain.project.models import Project


class ProjectLookup(Protocol):
    """Workspace-bound project existence and listing."""

    def get(self, project_id: str) -> Project | None: ...

    def list(self) -> tuple[Project, ...]: ...


@dataclass(frozen=True, slots=True)
class MembershipGrantProjectAccessPolicy:
    """Default-deny policy: active membership + explicit active project grant.

    Role strings on membership rows are ignored; #456 owns RBAC evaluation.
    """

    memberships: MembershipStore
    grants: ProjectGrantStore
    projects: ProjectLookup
    bound_workspace_id: str

    def can_read(self, caller: ProjectAccessCaller, project_id: str) -> bool:
        """Return whether *caller* may read *project_id*."""
        if caller.workspace_id != self.bound_workspace_id:
            return False
        membership = self.memberships.get_membership(
            caller.principal.user_id, caller.workspace_id
        )
        if membership is None or membership.status != "active":
            return False
        if self.projects.get(project_id) is None:
            return False
        for grant in self.grants.list_project_grants(
            caller.principal.user_id, caller.workspace_id
        ):
            if grant.project_id == project_id and grant.status == "active":
                return True
        return False

    def readable_projects(self, caller: ProjectAccessCaller) -> tuple[str, ...]:
        """Return project ids in the intersection of grants and bound projects."""
        if caller.workspace_id != self.bound_workspace_id:
            return ()
        membership = self.memberships.get_membership(
            caller.principal.user_id, caller.workspace_id
        )
        if membership is None or membership.status != "active":
            return ()
        existing = {project.project_id for project in self.projects.list()}
        granted = {
            grant.project_id
            for grant in self.grants.list_project_grants(
                caller.principal.user_id, caller.workspace_id
            )
            if grant.status == "active"
        }
        return tuple(sorted(existing & granted))


@dataclass(frozen=True, slots=True)
class _UnitOfWorkProjectLookup:
    """Adapt a ProjectUnitOfWork store to ProjectLookup."""

    store: object

    def get(self, project_id: str) -> Project | None:
        with self.store.read() as tx:  # type: ignore[attr-defined]
            return tx.projects.get(project_id)

    def list(self) -> tuple[Project, ...]:
        with self.store.read() as tx:  # type: ignore[attr-defined]
            return tx.projects.list()


def build_membership_grant_policy(
    *,
    memberships: MembershipStore,
    grants: ProjectGrantStore,
    projects: ProjectLookup,
    bound_workspace_id: str,
) -> ProjectAccessPolicy:
    """Build the production default-deny project access policy."""
    return MembershipGrantProjectAccessPolicy(
        memberships=memberships,
        grants=grants,
        projects=projects,
        bound_workspace_id=bound_workspace_id,
    )
