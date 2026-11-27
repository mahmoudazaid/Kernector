"""Project grant store contract (#446)."""

from __future__ import annotations

import dataclasses

import pytest

from domain.auth.models import ProjectGrant, WorkspaceMembership
from domain.auth.ports import MembershipStore, ProjectGrantStore


class MembershipRequiredError(LookupError):
    """No active membership exists for the grant key."""


class _FakeMembershipStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], WorkspaceMembership] = {}

    def grant_membership(
        self, principal_id: str, workspace_id: str
    ) -> WorkspaceMembership:
        membership = WorkspaceMembership(
            principal_id=principal_id,
            workspace_id=workspace_id,
            role="member",
            status="active",
        )
        self._rows[(principal_id, workspace_id)] = membership
        return membership

    def get_membership(
        self, principal_id: str, workspace_id: str
    ) -> WorkspaceMembership | None:
        return self._rows.get((principal_id, workspace_id))

    def list_memberships(self, principal_id: str) -> tuple[WorkspaceMembership, ...]:
        return tuple(
            row for (pid, _), row in sorted(self._rows.items()) if pid == principal_id
        )

    def disable_membership(self, principal_id: str, workspace_id: str) -> bool:
        key = (principal_id, workspace_id)
        row = self._rows.get(key)
        if row is None:
            return False
        self._rows[key] = dataclasses.replace(row, status="disabled")
        return True

    def revoke_membership(self, principal_id: str, workspace_id: str) -> bool:
        key = (principal_id, workspace_id)
        row = self._rows.get(key)
        if row is None:
            return False
        self._rows[key] = dataclasses.replace(row, status="revoked")
        return True


class _FakeProjectGrantStore:
    """In-memory ProjectGrantStore that requires active membership."""

    def __init__(self, memberships: MembershipStore) -> None:
        self._memberships = memberships
        self._rows: dict[tuple[str, str, str], ProjectGrant] = {}

    def grant_project(
        self, principal_id: str, workspace_id: str, project_id: str
    ) -> ProjectGrant:
        membership = self._memberships.get_membership(principal_id, workspace_id)
        if membership is None or membership.status != "active":
            raise MembershipRequiredError("active membership required")
        grant = ProjectGrant(
            principal_id=principal_id,
            workspace_id=workspace_id,
            project_id=project_id,
            status="active",
        )
        self._rows[(principal_id, workspace_id, project_id)] = grant
        return grant

    def list_project_grants(
        self, principal_id: str, workspace_id: str
    ) -> tuple[ProjectGrant, ...]:
        return tuple(
            row
            for key, row in sorted(self._rows.items())
            if key[0] == principal_id and key[1] == workspace_id
        )

    def revoke_project_grant(
        self, principal_id: str, workspace_id: str, project_id: str
    ) -> bool:
        key = (principal_id, workspace_id, project_id)
        row = self._rows.get(key)
        if row is None:
            return False
        self._rows[key] = dataclasses.replace(row, status="revoked")
        return True


def test_project_grant_is_frozen() -> None:
    grant = ProjectGrant(
        principal_id="usr_alice",
        workspace_id="ws_acme",
        project_id="prj_one",
        status="active",
    )
    assert grant.project_id == "prj_one"
    with pytest.raises(dataclasses.FrozenInstanceError):
        grant.status = "revoked"  # type: ignore[misc]


def test_project_grant_store_grants_and_lists_within_workspace() -> None:
    memberships: MembershipStore = _FakeMembershipStore()
    memberships.grant_membership("usr_alice", "ws_acme")
    store: ProjectGrantStore = _FakeProjectGrantStore(memberships)
    store.grant_project("usr_alice", "ws_acme", "prj_one")
    store.grant_project("usr_alice", "ws_acme", "prj_two")
    memberships.grant_membership("usr_alice", "ws_beta")
    store.grant_project("usr_alice", "ws_beta", "prj_one")
    listed = store.list_project_grants("usr_alice", "ws_acme")
    assert [g.project_id for g in listed] == ["prj_one", "prj_two"]
    assert all(g.workspace_id == "ws_acme" for g in listed)


def test_project_grant_store_rejects_grant_without_active_membership() -> None:
    memberships: MembershipStore = _FakeMembershipStore()
    store: ProjectGrantStore = _FakeProjectGrantStore(memberships)
    with pytest.raises(MembershipRequiredError):
        store.grant_project("usr_alice", "ws_acme", "prj_one")
    memberships.grant_membership("usr_alice", "ws_acme")
    memberships.disable_membership("usr_alice", "ws_acme")
    with pytest.raises(MembershipRequiredError):
        store.grant_project("usr_alice", "ws_acme", "prj_one")


def test_project_grant_revoke_is_visible_on_next_list() -> None:
    memberships: MembershipStore = _FakeMembershipStore()
    memberships.grant_membership("usr_alice", "ws_acme")
    store: ProjectGrantStore = _FakeProjectGrantStore(memberships)
    store.grant_project("usr_alice", "ws_acme", "prj_one")
    assert store.revoke_project_grant("usr_alice", "ws_acme", "prj_one") is True
    listed = store.list_project_grants("usr_alice", "ws_acme")
    assert len(listed) == 1
    assert listed[0].status == "revoked"
