"""Membership-and-grant-backed ProjectAccessPolicy (#446)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from composition.auth.project_access import (
    MembershipGrantProjectAccessPolicy,
    _UnitOfWorkProjectLookup,
    build_membership_grant_policy,
)
from domain.auth.models import ProjectGrant, WorkspaceMembership
from domain.auth.principal import Principal
from domain.project.access import ProjectAccessCaller
from domain.project.models import Project
from infrastructure.auth.sql_store import SqlAuthStore
from infrastructure.project.sql_store import SqlProjectStore


class _MemMembership:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], WorkspaceMembership] = {}

    def grant_membership(
        self, principal_id: str, workspace_id: str
    ) -> WorkspaceMembership:
        row = WorkspaceMembership(
            principal_id=principal_id,
            workspace_id=workspace_id,
            role="member",
            status="active",
        )
        self.rows[(principal_id, workspace_id)] = row
        return row

    def get_membership(
        self, principal_id: str, workspace_id: str
    ) -> WorkspaceMembership | None:
        return self.rows.get((principal_id, workspace_id))

    def list_memberships(self, principal_id: str) -> tuple[WorkspaceMembership, ...]:
        return tuple(
            row for (pid, _), row in self.rows.items() if pid == principal_id
        )

    def disable_membership(self, principal_id: str, workspace_id: str) -> bool:
        key = (principal_id, workspace_id)
        row = self.rows.get(key)
        if row is None:
            return False
        self.rows[key] = dataclasses.replace(row, status="disabled")
        return True

    def revoke_membership(self, principal_id: str, workspace_id: str) -> bool:
        key = (principal_id, workspace_id)
        row = self.rows.get(key)
        if row is None:
            return False
        self.rows[key] = dataclasses.replace(row, status="revoked")
        return True


class _MemGrants:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], ProjectGrant] = {}

    def grant_project(
        self, principal_id: str, workspace_id: str, project_id: str
    ) -> ProjectGrant:
        grant = ProjectGrant(
            principal_id=principal_id,
            workspace_id=workspace_id,
            project_id=project_id,
            status="active",
        )
        self.rows[(principal_id, workspace_id, project_id)] = grant
        return grant

    def list_project_grants(
        self, principal_id: str, workspace_id: str
    ) -> tuple[ProjectGrant, ...]:
        return tuple(
            row
            for key, row in sorted(self.rows.items())
            if key[0] == principal_id and key[1] == workspace_id
        )

    def revoke_project_grant(
        self, principal_id: str, workspace_id: str, project_id: str
    ) -> bool:
        key = (principal_id, workspace_id, project_id)
        row = self.rows.get(key)
        if row is None:
            return False
        self.rows[key] = dataclasses.replace(row, status="revoked")
        return True


class _MemProjects:
    def __init__(self, projects: dict[str, Project] | None = None) -> None:
        self._projects = dict(projects or {})

    def get(self, project_id: str) -> Project | None:
        return self._projects.get(project_id)

    def list(self) -> tuple[Project, ...]:
        return tuple(self._projects[pid] for pid in sorted(self._projects))


def _caller(workspace_id: str = "ws_acme") -> ProjectAccessCaller:
    return ProjectAccessCaller(
        principal=Principal(user_id="usr_alice", username="alice"),
        workspace_id=workspace_id,
    )


def _policy(
    *,
    memberships: _MemMembership | None = None,
    grants: _MemGrants | None = None,
    projects: _MemProjects | None = None,
    bound_workspace_id: str = "ws_acme",
) -> MembershipGrantProjectAccessPolicy:
    return MembershipGrantProjectAccessPolicy(
        memberships=memberships or _MemMembership(),
        grants=grants or _MemGrants(),
        projects=projects or _MemProjects(),
        bound_workspace_id=bound_workspace_id,
    )


def test_empty_stores_deny_all() -> None:
    policy = _policy()
    caller = _caller()
    assert policy.can_read(caller, "prj_one") is False
    assert policy.readable_projects(caller) == ()


def test_active_membership_and_grant_and_existing_project_allows_read() -> None:
    mem = _MemMembership()
    grants = _MemGrants()
    mem.grant_membership("usr_alice", "ws_acme")
    grants.grant_project("usr_alice", "ws_acme", "prj_one")
    projects = _MemProjects({"prj_one": Project("prj_one", "One", "one", 1)})
    policy = _policy(memberships=mem, grants=grants, projects=projects)
    assert policy.can_read(_caller(), "prj_one") is True
    assert policy.readable_projects(_caller()) == ("prj_one",)


def test_membership_without_grant_denies_project() -> None:
    mem = _MemMembership()
    mem.grant_membership("usr_alice", "ws_acme")
    projects = _MemProjects({"prj_one": Project("prj_one", "One", "one", 1)})
    policy = _policy(memberships=mem, projects=projects)
    assert policy.can_read(_caller(), "prj_one") is False
    assert policy.readable_projects(_caller()) == ()


def test_disabled_or_revoked_membership_denies_even_with_grant() -> None:
    mem = _MemMembership()
    grants = _MemGrants()
    mem.grant_membership("usr_alice", "ws_acme")
    grants.grant_project("usr_alice", "ws_acme", "prj_one")
    projects = _MemProjects({"prj_one": Project("prj_one", "One", "one", 1)})
    policy = _policy(memberships=mem, grants=grants, projects=projects)
    mem.disable_membership("usr_alice", "ws_acme")
    assert policy.can_read(_caller(), "prj_one") is False
    mem.grant_membership("usr_alice", "ws_acme")
    mem.revoke_membership("usr_alice", "ws_acme")
    assert policy.can_read(_caller(), "prj_one") is False


def test_revoked_grant_denies_project() -> None:
    mem = _MemMembership()
    grants = _MemGrants()
    mem.grant_membership("usr_alice", "ws_acme")
    grants.grant_project("usr_alice", "ws_acme", "prj_one")
    grants.revoke_project_grant("usr_alice", "ws_acme", "prj_one")
    projects = _MemProjects({"prj_one": Project("prj_one", "One", "one", 1)})
    policy = _policy(memberships=mem, grants=grants, projects=projects)
    assert policy.can_read(_caller(), "prj_one") is False


def test_grant_for_wrong_workspace_does_not_authorize() -> None:
    mem = _MemMembership()
    grants = _MemGrants()
    mem.grant_membership("usr_alice", "ws_other")
    grants.grant_project("usr_alice", "ws_other", "prj_one")
    mem.grant_membership("usr_alice", "ws_acme")
    projects = _MemProjects({"prj_one": Project("prj_one", "One", "one", 1)})
    policy = _policy(memberships=mem, grants=grants, projects=projects)
    assert policy.can_read(_caller("ws_acme"), "prj_one") is False


def test_readable_projects_is_intersection_of_grants_and_workspace_projects() -> None:
    mem = _MemMembership()
    grants = _MemGrants()
    mem.grant_membership("usr_alice", "ws_acme")
    grants.grant_project("usr_alice", "ws_acme", "prj_one")
    grants.grant_project("usr_alice", "ws_acme", "prj_gone")
    projects = _MemProjects(
        {
            "prj_one": Project("prj_one", "One", "one", 1),
            "prj_two": Project("prj_two", "Two", "two", 1),
        }
    )
    policy = _policy(memberships=mem, grants=grants, projects=projects)
    assert policy.readable_projects(_caller()) == ("prj_one",)


def test_caller_workspace_mismatch_with_bound_store_denies() -> None:
    mem = _MemMembership()
    grants = _MemGrants()
    mem.grant_membership("usr_alice", "ws_other")
    grants.grant_project("usr_alice", "ws_other", "prj_one")
    projects = _MemProjects({"prj_one": Project("prj_one", "One", "one", 1)})
    policy = _policy(
        memberships=mem,
        grants=grants,
        projects=projects,
        bound_workspace_id="ws_acme",
    )
    assert policy.can_read(_caller("ws_other"), "prj_one") is False


def test_sql_backed_policy_allows_granted_project_only(tmp_path: Path) -> None:
    auth = SqlAuthStore(tmp_path / "auth.sqlite")
    projects = SqlProjectStore(tmp_path / "catalog.sqlite", "ws_acme")
    user = auth.create_user("alice", "secret-password")
    with projects.transaction() as tx:
        tx.projects.add(Project("prj_one", "One", "one", 1))
        tx.projects.add(Project("prj_two", "Two", "two", 1))
    auth.grant_membership(user.user_id, "ws_acme")
    auth.grant_project(user.user_id, "ws_acme", "prj_one")
    policy = build_membership_grant_policy(
        memberships=auth,
        grants=auth,
        projects=_UnitOfWorkProjectLookup(projects),
        bound_workspace_id="ws_acme",
    )
    caller = ProjectAccessCaller(
        principal=Principal(user_id=user.user_id, username="alice"),
        workspace_id="ws_acme",
    )
    assert policy.can_read(caller, "prj_one") is True
    assert policy.can_read(caller, "prj_two") is False
    assert policy.readable_projects(caller) == ("prj_one",)
    auth.disable_membership(user.user_id, "ws_acme")
    assert policy.can_read(caller, "prj_one") is False
