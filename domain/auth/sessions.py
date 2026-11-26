"""Opaque session id helpers (#182)."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_session_id() -> str:
    """Return a cryptographically secure opaque session id."""
    return secrets.token_urlsafe(32)


def hash_session_id(session_id: str) -> str:
    """Return a SHA-256 hex digest of *session_id* for at-rest storage."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def session_ids_match(session_id: str, session_id_hash: str) -> bool:
    """Constant-time compare of *session_id* against a stored hash."""
    return hmac.compare_digest(hash_session_id(session_id), session_id_hash)
