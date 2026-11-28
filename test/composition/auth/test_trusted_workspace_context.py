"""Trusted workspace selection and ProjectAccessCaller resolution (#447)."""

from __future__ import annotations

import dataclasses

import pytest

from composition.auth.trusted_context import (
    NoActiveMembershipError,
    TrustedWorkspaceSelectionRequiredError,
    resolve_trusted_project_access_caller,
    select_trusted_workspace,
)
from domain.auth.models import WorkspaceMembership
from domain.auth.principal import Principal


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


def _principal() -> Principal:
    return Principal(user_id="usr_alice", username="alice")


def test_resolve_returns_caller_when_active_membership_exists() -> None:
    store = _MemMembership()
    store.grant_membership("usr_alice", "ws_acme")
    caller = resolve_trusted_project_access_caller(
        _principal(), "ws_acme", store
    )
    assert caller.principal.user_id == "usr_alice"
    assert caller.workspace_id == "ws_acme"


def test_resolve_rejects_missing_membership() -> None:
    with pytest.raises(NoActiveMembershipError):
        resolve_trusted_project_access_caller(
            _principal(), "ws_acme", _MemMembership()
        )


def test_resolve_rejects_inactive_membership() -> None:
    store = _MemMembership()
    store.grant_membership("usr_alice", "ws_acme")
    store.disable_membership("usr_alice", "ws_acme")
    with pytest.raises(NoActiveMembershipError):
        resolve_trusted_project_access_caller(
            _principal(), "ws_acme", store
        )


def test_select_denies_zero_active_memberships() -> None:
    with pytest.raises(NoActiveMembershipError):
        select_trusted_workspace(_principal(), _MemMembership())


def test_select_auto_selects_single_active_membership() -> None:
    store = _MemMembership()
    store.grant_membership("usr_alice", "ws_acme")
    assert select_trusted_workspace(_principal(), store) == "ws_acme"


def test_select_ignores_inactive_when_counting_active() -> None:
    store = _MemMembership()
    store.grant_membership("usr_alice", "ws_old")
    store.revoke_membership("usr_alice", "ws_old")
    store.grant_membership("usr_alice", "ws_acme")
    assert select_trusted_workspace(_principal(), store) == "ws_acme"


def test_select_requires_session_selection_when_multiple_active() -> None:
    store = _MemMembership()
    store.grant_membership("usr_alice", "ws_a")
    store.grant_membership("usr_alice", "ws_b")
    with pytest.raises(TrustedWorkspaceSelectionRequiredError):
        select_trusted_workspace(_principal(), store)


def test_select_prefers_process_bound_workspace_among_multiple_active() -> None:
    store = _MemMembership()
    store.grant_membership("usr_alice", "ws_a")
    store.grant_membership("usr_alice", "ws_b")
    assert (
        select_trusted_workspace(
            _principal(),
            store,
            preferred_workspace_id="ws_b",
        )
        == "ws_b"
    )


def test_select_session_selection_overrides_preferred_workspace() -> None:
    store = _MemMembership()
    store.grant_membership("usr_alice", "ws_a")
    store.grant_membership("usr_alice", "ws_b")
    assert (
        select_trusted_workspace(
            _principal(),
            store,
            session_selected_workspace_id="ws_a",
            preferred_workspace_id="ws_b",
        )
        == "ws_a"
    )


def test_select_accepts_membership_validated_session_selection() -> None:
    store = _MemMembership()
    store.grant_membership("usr_alice", "ws_a")
    store.grant_membership("usr_alice", "ws_b")
    assert (
        select_trusted_workspace(
            _principal(),
            store,
            session_selected_workspace_id="ws_b",
        )
        == "ws_b"
    )


def test_select_rejects_session_selection_without_active_membership() -> None:
    store = _MemMembership()
    store.grant_membership("usr_alice", "ws_a")
    store.grant_membership("usr_alice", "ws_b")
    with pytest.raises(NoActiveMembershipError):
        select_trusted_workspace(
            _principal(),
            store,
            session_selected_workspace_id="ws_foreign",
        )


def test_bootstrap_constrains_to_env_workspace_with_membership() -> None:
    store = _MemMembership()
    store.grant_membership("usr_alice", "ws_boot")
    store.grant_membership("usr_alice", "ws_other")
    assert (
        select_trusted_workspace(
            _principal(),
            store,
            bootstrap_workspace_id="ws_boot",
        )
        == "ws_boot"
    )


def test_bootstrap_still_requires_active_membership() -> None:
    with pytest.raises(NoActiveMembershipError):
        select_trusted_workspace(
            _principal(),
            _MemMembership(),
            bootstrap_workspace_id="ws_boot",
        )


def test_bootstrap_rejects_membership_outside_bootstrap_workspace() -> None:
    store = _MemMembership()
    store.grant_membership("usr_alice", "ws_other")
    with pytest.raises(NoActiveMembershipError):
        select_trusted_workspace(
            _principal(),
            store,
            bootstrap_workspace_id="ws_boot",
        )
