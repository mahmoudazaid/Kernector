"""SQLite auth store (#182)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from infrastructure.auth.errors import DuplicateUsernameError, UserNotFoundError
from infrastructure.auth.sql_store import SqlAuthStore


def test_create_user_and_authenticate(tmp_path: Path) -> None:
    store = SqlAuthStore(tmp_path / "auth.sqlite")
    created = store.create_user("alice", "secret-password")
    assert created.username == "alice"
    assert created.user_id.startswith("usr_")
    assert "secret-password" not in created.password_hash
    principal = store.authenticate("alice", "secret-password")
    assert principal is not None
    assert principal.user_id == created.user_id
    assert principal.username == "alice"
    assert store.authenticate("alice", "wrong") is None
    assert store.authenticate("missing", "secret-password") is None


def test_create_user_rejects_duplicate_username(tmp_path: Path) -> None:
    store = SqlAuthStore(tmp_path / "auth.sqlite")
    store.create_user("alice", "secret-password")
    with pytest.raises(DuplicateUsernameError):
        store.create_user("alice", "other-password")


def test_session_lifecycle_issue_lookup_revoke_expire(tmp_path: Path) -> None:
    store = SqlAuthStore(tmp_path / "auth.sqlite")
    user = store.create_user("alice", "secret-password")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    session_id, stored = store.create_session(
        user.user_id, ttl_seconds=3600, now=now
    )
    assert stored.user_id == user.user_id
    assert store.get_session(session_id, now=now) == stored
    assert store.get_session(session_id, now=now + timedelta(hours=2)) is None

    session_id2, _ = store.create_session(user.user_id, ttl_seconds=3600, now=now)
    assert store.revoke_session(session_id2, now=now) is True
    assert store.get_session(session_id2, now=now) is None


def test_preferences_get_put_scoped_to_user(tmp_path: Path) -> None:
    store = SqlAuthStore(tmp_path / "auth.sqlite")
    alice = store.create_user("alice", "secret-a")
    bob = store.create_user("bob", "secret-b")
    assert store.get_preferences(alice.user_id) is None
    saved = store.put_preferences(
        alice.user_id, provider="ollama", model="llama3"
    )
    assert saved.provider == "ollama"
    assert store.get_preferences(alice.user_id) == saved
    assert store.get_preferences(bob.user_id) is None


def test_put_preferences_unknown_user_raises(tmp_path: Path) -> None:
    store = SqlAuthStore(tmp_path / "auth.sqlite")
    with pytest.raises(UserNotFoundError):
        store.put_preferences("usr_missing", provider="ollama", model="x")


def test_login_attempt_counter_and_lockout(tmp_path: Path) -> None:
    store = SqlAuthStore(tmp_path / "auth.sqlite")
    store.create_user("alice", "secret-password")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    first = store.record_login_failure(
        "alice", max_failures=3, lockout_seconds=600, now=now
    )
    assert first.failure_count == 1
    assert first.locked_until is None
    assert store.is_locked("alice", now=now) is False
    store.record_login_failure(
        "alice", max_failures=3, lockout_seconds=600, now=now
    )
    locked = store.record_login_failure(
        "alice", max_failures=3, lockout_seconds=600, now=now
    )
    assert locked.failure_count == 3
    assert locked.locked_until is not None
    assert store.is_locked("alice", now=now) is True
    assert store.is_locked("alice", now=now + timedelta(seconds=601)) is False
    # After lockout expires, the next failure starts a fresh window at 1.
    after = store.record_login_failure(
        "alice",
        max_failures=3,
        lockout_seconds=600,
        now=now + timedelta(seconds=601),
    )
    assert after.failure_count == 1
    assert after.locked_until is None
    store.clear_login_attempts("alice")
    assert store.get_login_attempts("alice") is None


def test_claim_login_attempt_returns_locked_while_locked(tmp_path: Path) -> None:
    store = SqlAuthStore(tmp_path / "auth.sqlite")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for _ in range(3):
        store.claim_login_attempt(
            "alice", max_failures=3, lockout_seconds=600, now=now
        )
    assert (
        store.claim_login_attempt(
            "alice", max_failures=3, lockout_seconds=600, now=now
        )
        == "locked"
    )


def test_user_id_stable_across_sessions(tmp_path: Path) -> None:
    store = SqlAuthStore(tmp_path / "auth.sqlite")
    user = store.create_user("alice", "secret-password")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    sid1, s1 = store.create_session(user.user_id, ttl_seconds=60, now=now)
    sid2, s2 = store.create_session(
        user.user_id, ttl_seconds=60, now=now + timedelta(seconds=1)
    )
    assert sid1 != sid2
    assert s1.user_id == s2.user_id == user.user_id
