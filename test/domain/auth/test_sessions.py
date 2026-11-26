"""Domain session id helpers (#182)."""

from __future__ import annotations

from domain.auth.sessions import (
    generate_session_id,
    hash_session_id,
    session_ids_match,
)


def test_generate_session_id_returns_urlsafe_opaque_token() -> None:
    token = generate_session_id()
    assert len(token) >= 32
    assert hash_session_id(token) != token


def test_session_ids_match_is_constant_time_equality() -> None:
    token = generate_session_id()
    digest = hash_session_id(token)
    assert session_ids_match(token, digest) is True
    assert session_ids_match("other-token", digest) is False
