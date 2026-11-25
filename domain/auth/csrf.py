"""Session-bound CSRF tokens derived from a server-only key (#182)."""

from __future__ import annotations

import hashlib
import hmac


def derive_csrf_token(server_key: bytes, session_id: str) -> str:
    """Return HMAC-SHA256(*server_key*, *session_id*) as urlsafe hex.

    The value is re-derived on every request from the session cookie and
    ``AUTH_CSRF_KEY``. It is not stored and is not rotated by ``GET /me``.
    """
    digest = hmac.new(
        server_key,
        session_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def csrf_tokens_match(presented: str, expected: str) -> bool:
    """Constant-time compare of presented and expected CSRF tokens."""
    return hmac.compare_digest(presented, expected)
