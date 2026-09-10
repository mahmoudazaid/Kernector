"""Drive folder ID charset contract shared by settings consumers."""

from __future__ import annotations

import re

# fullmatch is load-bearing: .match()/.search() would accept injection prefixes.
_DRIVE_FOLDER_ID = re.compile(r"[A-Za-z0-9_-]+")
DRIVE_FOLDER_ID_CONTRACT = (
    "must be a Drive folder ID (letters, digits, `-`, `_`); "
    "it looks like you pasted a URL or path"
)


def is_drive_folder_id(raw: str) -> bool:
    """Return whether ``raw`` matches the Drive folder ID charset."""
    return bool(_DRIVE_FOLDER_ID.fullmatch(raw))


def require_drive_folder_id(raw: str) -> str:
    """Return ``raw`` or raise ``ValueError`` naming ``GOOGLE_DRIVE_FOLDER_ID``.

    Args:
        raw: Candidate folder ID (already stripped).

    Returns:
        The same string when valid.

    Raises:
        ValueError: The value fails the charset contract.
    """
    if not is_drive_folder_id(raw):
        raise ValueError(f"GOOGLE_DRIVE_FOLDER_ID {DRIVE_FOLDER_ID_CONTRACT}")
    return raw
