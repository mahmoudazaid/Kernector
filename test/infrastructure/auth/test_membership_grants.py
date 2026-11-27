"""SQLite membership and project-grant isolation (#446)."""

from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.auth.errors import MembershipRequiredError, UserNotFoundError
from infrastructure.auth.sql_store import SqlAuthStore


def _store(tmp_path: Path) -> SqlAuthStore:
    return SqlAuthStore(tmp_path / "auth.sqlite")


def test_two_principals_have_different_memberships_and_grants(tmp_path: Path) -> None:
    store = _store(tmp_path)
    alice = store.create_user("alice", "secret-a")
    bob = store.create_user("bob", "secret-b")
    store.grant_membership(alice.user_id, "ws_acme")
    store.grant_membership(bob.user_id, "ws_beta")
    store.grant_project(alice.user_id, "ws_acme", "prj_shared")
    store.grant_project(bob.user_id, "ws_beta", "prj_shared")

    alice_memberships = store.list_memberships(alice.user_id)
    bob_memberships = store.list_memberships(bob.user_id)
    assert [m.workspace_id for m in alice_memberships] == ["ws_acme"]
    assert [m.workspace_id for m in bob_memberships] == ["ws_beta"]
    assert [
        g.project_id for g in store.list_project_grants(alice.user_id, "ws_acme")
    ] == ["prj_shared"]
    assert store.list_project_grants(alice.user_id, "ws_beta") == ()
    assert [
        g.project_id for g in store.list_project_grants(bob.user_id, "ws_beta")
    ] == ["prj_shared"]
    assert store.list_project_grants(bob.user_id, "ws_acme") == ()


def test_grant_in_workspace_a_does_not_appear_under_workspace_b(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    alice = store.create_user("alice", "secret-a")
    store.grant_membership(alice.user_id, "ws_a")
    store.grant_membership(alice.user_id, "ws_b")
    store.grant_project(alice.user_id, "ws_a", "prj_one")
    assert store.list_project_grants(alice.user_id, "ws_b") == ()
    grants_a = store.list_project_grants(alice.user_id, "ws_a")
    assert len(grants_a) == 1
    assert grants_a[0].workspace_id == "ws_a"
    assert grants_a[0].project_id == "prj_one"


def test_absent_disabled_or_revoked_membership_blocks_new_grants(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    alice = store.create_user("alice", "secret-a")
    with pytest.raises(MembershipRequiredError):
        store.grant_project(alice.user_id, "ws_acme", "prj_one")

    store.grant_membership(alice.user_id, "ws_acme")
    store.disable_membership(alice.user_id, "ws_acme")
    with pytest.raises(MembershipRequiredError):
        store.grant_project(alice.user_id, "ws_acme", "prj_one")

    store.grant_membership(alice.user_id, "ws_acme")
    store.revoke_membership(alice.user_id, "ws_acme")
    with pytest.raises(MembershipRequiredError):
        store.grant_project(alice.user_id, "ws_acme", "prj_one")


def test_revoked_project_grant_is_visible_on_next_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    alice = store.create_user("alice", "secret-a")
    store.grant_membership(alice.user_id, "ws_acme")
    store.grant_project(alice.user_id, "ws_acme", "prj_one")
    assert store.revoke_project_grant(alice.user_id, "ws_acme", "prj_one") is True
    listed = store.list_project_grants(alice.user_id, "ws_acme")
    assert len(listed) == 1
    assert listed[0].status == "revoked"


def test_membership_status_mutations_visible_on_next_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    alice = store.create_user("alice", "secret-a")
    store.grant_membership(alice.user_id, "ws_acme")
    assert store.get_membership(alice.user_id, "ws_acme") is not None
    assert store.get_membership(alice.user_id, "ws_acme").status == "active"
    store.disable_membership(alice.user_id, "ws_acme")
    assert store.get_membership(alice.user_id, "ws_acme").status == "disabled"
    store.revoke_membership(alice.user_id, "ws_acme")
    assert store.get_membership(alice.user_id, "ws_acme").status == "revoked"


def test_grant_membership_unknown_user_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(UserNotFoundError):
        store.grant_membership("usr_missing", "ws_acme")


def test_grant_membership_rejects_invalid_workspace_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    alice = store.create_user("alice", "secret-a")
    with pytest.raises(ValueError, match="workspace_id"):
        store.grant_membership(alice.user_id, "bad workspace")
