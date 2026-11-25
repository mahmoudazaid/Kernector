"""Domain CSRF derivation (#182)."""

from __future__ import annotations

from domain.auth.csrf import derive_csrf_token, csrf_tokens_match


def test_derive_csrf_token_is_stable_for_same_session_and_key() -> None:
    key = b"server-only-csrf-key-32-bytes-ok!!"
    session_id = "session-opaque-value"
    first = derive_csrf_token(key, session_id)
    second = derive_csrf_token(key, session_id)
    assert first == second
    assert len(first) >= 32


def test_derive_csrf_token_changes_when_session_or_key_changes() -> None:
    key = b"server-only-csrf-key-32-bytes-ok!!"
    other_key = b"different-csrf-key-32-bytes-long!"
    session_id = "session-opaque-value"
    token = derive_csrf_token(key, session_id)
    assert token != derive_csrf_token(other_key, session_id)
    assert token != derive_csrf_token(key, "other-session")


def test_csrf_tokens_match_rejects_mismatch() -> None:
    key = b"server-only-csrf-key-32-bytes-ok!!"
    token = derive_csrf_token(key, "session-a")
    assert csrf_tokens_match(token, token) is True
    assert csrf_tokens_match(token, derive_csrf_token(key, "session-b")) is False


def test_derive_csrf_token_does_not_mutate_session_id() -> None:
    key = b"server-only-csrf-key-32-bytes-ok!!"
    session_id = "immutable-session"
    before = session_id
    _ = derive_csrf_token(key, session_id)
    assert session_id == before
