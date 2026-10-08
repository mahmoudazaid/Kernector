"""Authoritative Jira issue locator parsing: ``PROJ-123`` and ``<base>/browse/PROJ-123``.

Browse URLs are accepted only for the configured instance: same scheme, host,
effective port and context path, with the exact ``/browse/{KEY}`` structure.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from urllib.parse import urlsplit

_KEY = r"[A-Z][A-Z0-9_]+-[1-9][0-9]*"
_KEY_PATTERN = re.compile(_KEY)
# Bare keys in prose: any case (only selected projects are taken), never inside
# a path, ref or longer token.
_BARE_KEY_IN_TEXT = re.compile(
    rf"(?<![A-Za-z0-9_/#.\-])(?P<key>{_KEY})(?![A-Za-z0-9_\-])", re.IGNORECASE
)
_URL_IN_TEXT = re.compile(r"https?://[^\s<>()\[\]{}\"'`]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?"
_DEFAULT_PORTS = {"https": 443, "http": 80}


class InvalidJiraIssueLocatorError(ValueError):
    """Locator string is not a single well-formed Jira issue reference."""


class AmbiguousJiraIssueLocatorError(ValueError):
    """Text contains more than one distinct Jira issue reference."""


@dataclass(frozen=True, slots=True)
class JiraBrowseBase:
    """Normalized configured instance that browse URLs must match exactly."""

    scheme: str
    host: str
    port: int
    context: str

    @classmethod
    def parse(cls, base_url: str) -> JiraBrowseBase | None:
        """Return the normalized instance, or ``None`` for an unusable base URL."""
        try:
            parts = urlsplit(base_url.strip())
            port = parts.port
        except ValueError:
            return None
        scheme = parts.scheme.lower()
        host = _normalize_host(parts.hostname)
        if scheme not in _DEFAULT_PORTS or not host:
            return None
        return cls(
            scheme=scheme,
            host=host,
            port=port or _DEFAULT_PORTS[scheme],
            context=parts.path.rstrip("/"),
        )


def canonicalize_jira_issue_locator(text: str, *, base: JiraBrowseBase | None) -> str:
    """Return the canonical uppercase key or raise ``InvalidJiraIssueLocatorError``.

    Any syntactically valid key is accepted; project selection is not consulted.
    """
    key = _parse_locator(text, base=base)
    if key is None:
        raise InvalidJiraIssueLocatorError(
            "Jira issue locator must be an issue key or a browse URL of the "
            "configured instance"
        )
    return key


def extract_jira_issue_locator(
    text: str,
    *,
    base: JiraBrowseBase | None,
    project_keys: Collection[str],
) -> str | None:
    """Extract exactly one issue from free text.

    Browse URLs of the configured instance are extracted regardless of
    ``project_keys``; bare keys (any case, returned uppercase) only when their
    project is listed.
    Duplicate mentions are accepted; several distinct issues raise
    ``AmbiguousJiraIssueLocatorError``.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    found: set[str] = set()
    for match in _URL_IN_TEXT.finditer(text):
        key = _key_from_browse_url(match.group(0).rstrip(_TRAILING_PUNCTUATION), base)
        if key is not None:
            found.add(key)
    allowed = {project.upper() for project in project_keys}
    for match in _BARE_KEY_IN_TEXT.finditer(text):
        key = match.group("key").upper()
        if key.rsplit("-", 1)[0] in allowed:
            found.add(key)
    if len(found) > 1:
        raise AmbiguousJiraIssueLocatorError("Query must reference exactly one Jira issue")
    return next(iter(found), None)


def is_jira_issue_key(value: str) -> bool:
    """Return whether *value* is a canonical (uppercase) issue key."""
    return isinstance(value, str) and _KEY_PATTERN.fullmatch(value) is not None


def _parse_locator(text: object, *, base: JiraBrowseBase | None) -> str | None:
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped or not stripped.isascii() or _has_space_or_control(stripped):
        return None
    if "://" in stripped:
        return _key_from_browse_url(stripped, base)
    key = stripped.upper()
    return key if _KEY_PATTERN.fullmatch(key) else None


def _key_from_browse_url(url: str, base: JiraBrowseBase | None) -> str | None:
    if base is None or not url.isascii() or _has_space_or_control(url):
        return None
    if "?" in url or "#" in url:
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme != base.scheme or "@" in parts.netloc:
        return None
    if _normalize_host(parts.hostname) != base.host:
        return None
    if (port or _DEFAULT_PORTS[scheme]) != base.port:
        return None
    prefix = f"{base.context}/browse/"
    if not parts.path.startswith(prefix):
        return None
    key = parts.path[len(prefix):].upper()
    return key if _KEY_PATTERN.fullmatch(key) else None


def _normalize_host(host: str | None) -> str:
    return (host or "").rstrip(".").lower()


def _has_space_or_control(value: str) -> bool:
    return any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value)
