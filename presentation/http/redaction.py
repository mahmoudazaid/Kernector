"""Redact auth secrets from log and error text (#182)."""

from __future__ import annotations

import re

# JSON ("password": "…") and key=value / key: value forms.
_PASSWORD_KEYS = re.compile(
    r'(?i)(["\']?(?:password|passwd|pwd)["\']?\s*[:=]\s*)'
    r'(?:"([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\'|([^\s,;]+))'
)
_COOKIE_SESSION = re.compile(
    r"(?i)(kernector_session)=([^;\s]+)"
)
_CSRF_HEADER = re.compile(
    r'(?i)(["\']?(?:x-csrf-token|csrf_token)["\']?\s*[:=]\s*)'
    r'(?:"([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\'|([^\s,;]+))'
)


def _redact_match(match: re.Match[str]) -> str:
    prefix = match.group(1)
    return f"{prefix}[REDACTED]" if not prefix.endswith('"') else f'{prefix}"[REDACTED]"'


def redact_secrets(text: str) -> str:
    """Return *text* with passwords, session cookies, and CSRF tokens masked."""

    def _sub_quoted(match: re.Match[str]) -> str:
        prefix = match.group(1)
        # Preserve JSON quoting style when the value was quoted.
        if match.group(2) is not None:
            return f'{prefix}"[REDACTED]"'
        if match.group(3) is not None:
            return f"{prefix}'[REDACTED]'"
        return f"{prefix}[REDACTED]"

    out = _PASSWORD_KEYS.sub(_sub_quoted, text)
    out = _COOKIE_SESSION.sub(r"\1=[REDACTED]", out)
    out = _CSRF_HEADER.sub(_sub_quoted, out)
    return out
