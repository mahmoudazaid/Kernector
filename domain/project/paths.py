"""Provider-neutral path-prefix rules for component membership.

A canonical prefix is ``""`` (the whole scope) or ``seg(/seg)*``. Matching is
case-sensitive and respects directory boundaries: ``web`` matches
``web/app.tsx`` and ``web`` but never ``website/app.tsx``.
"""

from __future__ import annotations

from domain.project.errors import ProjectInputError

MAX_PATH_LENGTH = 1024


def _segments_valid(path: str) -> bool:
    if len(path) > MAX_PATH_LENGTH or "\\" in path:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        return False
    return all(segment not in ("", ".", "..") for segment in path.split("/"))


def is_valid_path(path: object) -> bool:
    """Return whether ``path`` is a non-empty canonical relative path."""
    return isinstance(path, str) and path != "" and _segments_valid(path)


def normalize_path_prefix(raw: str) -> str:
    """Return the canonical form of ``raw``, removing one trailing ``/``.

    Raises:
        ProjectInputError: ``raw`` is absolute, has empty, ``.`` or ``..``
            segments, backslashes or control characters, or is too long.
    """
    if not isinstance(raw, str):
        raise ProjectInputError(
            f"path_prefix must be a string, got {type(raw).__name__}"
        )
    if raw == "":
        return ""
    prefix = raw[:-1] if raw.endswith("/") else raw
    if not is_valid_path(prefix):
        raise ProjectInputError(
            "path_prefix must be a relative path without empty, '.' or '..' "
            "segments, backslashes or control characters"
        )
    return prefix


def prefix_matches(prefix: str, path: str) -> bool:
    """Return whether canonical ``prefix`` covers ``path``."""
    return prefix == "" or path == prefix or path.startswith(prefix + "/")


def prefix_depth(prefix: str) -> int:
    """Return the number of segments in canonical ``prefix``."""
    return 0 if prefix == "" else prefix.count("/") + 1
