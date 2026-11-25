"""Redact auth secrets from log and error text (#182)."""

from __future__ import annotations

import re

_PASSWORD_KEYS = re.compile(
    r"(?i)(password|passwd|pwd)\s*[:=]\s*([^\s,;]+)"
)
_COOKIE_SESSION = re.compile(
    r"(?i)(kernector_session)=([^;\s]+)"
)
_CSRF_HEADER = re.compile(
    r"(?i)(x-csrf-token|csrf_token)\s*[:=]\s*([^\s,;]+)"
)


def redact_secrets(text: str) -> str:
    """Return *text* with passwords, session cookies, and CSRF tokens masked."""
    out = _PASSWORD_KEYS.sub(r"\1=[REDACTED]", text)
    out = _COOKIE_SESSION.sub(r"\1=[REDACTED]", out)
    out = _CSRF_HEADER.sub(r"\1=[REDACTED]", out)
    return out
