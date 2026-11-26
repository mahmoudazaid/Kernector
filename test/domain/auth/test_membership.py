"""Workspace membership store contract (#446)."""

from __future__ import annotations

import dataclasses
from typing import Literal

import pytest

from domain.auth.models import MEMBER_ROLE, MembershipStatus, WorkspaceMembership
from domain.auth.ports import MembershipStore


class _FakeMembershipStore:
    """In-memory MembershipStore for domain contract tests."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], WorkspaceMembership] = {}

    def grant_membership(
        self, principal_id: str, workspace_id: str
    ) -> WorkspaceMembership:
        key = (principal_id, workspace_id)
        membership = WorkspaceMembership(
            principal_id=principal_id,
            workspace_id=workspace_id,
            role=MEMBER_ROLE,
            status="active",
        )
        self._rows[key] = membership
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


def test_workspace_membership_is_frozen_with_opaque_member_role() -> None:
    membership = WorkspaceMembership(
        principal_id="usr_alice",
        workspace_id="ws_acme",
        role=MEMBER_ROLE,
        status="active",
    )
    assert membership.role == "member"
    assert membership.status == "active"
    with pytest.raises(dataclasses.FrozenInstanceError):
        membership.status = "revoked"  # type: ignore[misc]


def test_membership_store_grants_active_membership_with_opaque_member_role() -> None:
    store: MembershipStore = _FakeMembershipStore()
    granted = store.grant_membership("usr_alice", "ws_acme")
    assert granted == WorkspaceMembership(
        principal_id="usr_alice",
        workspace_id="ws_acme",
        role="member",
        status="active",
    )
    assert store.get_membership("usr_alice", "ws_acme") == granted


def test_membership_store_lists_memberships_for_one_principal() -> None:
    store: MembershipStore = _FakeMembershipStore()
    store.grant_membership("usr_alice", "ws_acme")
    store.grant_membership("usr_alice", "ws_beta")
    store.grant_membership("usr_bob", "ws_acme")
    listed = store.list_memberships("usr_alice")
    assert [m.workspace_id for m in listed] == ["ws_acme", "ws_beta"]
    assert all(m.principal_id == "usr_alice" for m in listed)


def test_membership_store_disable_and_revoke_change_status_on_next_read() -> None:
    store: MembershipStore = _FakeMembershipStore()
    store.grant_membership("usr_alice", "ws_acme")
    assert store.disable_membership("usr_alice", "ws_acme") is True
    disabled = store.get_membership("usr_alice", "ws_acme")
    assert disabled is not None
    assert disabled.status == "disabled"
    assert store.revoke_membership("usr_alice", "ws_acme") is True
    revoked = store.get_membership("usr_alice", "ws_acme")
    assert revoked is not None
    assert revoked.status == "revoked"


def test_membership_status_literals_cover_active_disabled_revoked() -> None:
    statuses: tuple[MembershipStatus, ...] = ("active", "disabled", "revoked")
    assert statuses == ("active", "disabled", "revoked")
    # Opaque role is never consulted for authorization in #446.
    role: Literal["member"] = MEMBER_ROLE
    assert role == "member"
