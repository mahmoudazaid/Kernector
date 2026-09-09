"""Shared SQLite connection setup for the SQL catalog and importer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from domain.knowledge import CatalogDocument

BUSY_TIMEOUT_MS = 5000
SELECT_COLUMNS = (
    "source_id, source_type, file_name, title, content_format, status, "
    "uploaded_at, chunk_count, error, revision"
)
_UPSERT_SQL = f"""
INSERT INTO catalog_documents (
    workspace_id, {SELECT_COLUMNS}
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (workspace_id, source_type, source_id) DO UPDATE SET
    file_name = excluded.file_name,
    title = excluded.title,
    content_format = excluded.content_format,
    status = excluded.status,
    uploaded_at = excluded.uploaded_at,
    chunk_count = excluded.chunk_count,
    error = excluded.error,
    revision = excluded.revision
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open a catalog SQLite connection with busy timeout and journal mode.

    Args:
        path (Path): SQLite database path.

    Returns:
        sqlite3.Connection: Autocommit connection; callers own transactions.
    """
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        connection.execute(f"PRAGMA journal_mode = {journal_mode()}")
    except Exception:
        connection.close()
        raise
    return connection


def journal_mode() -> str:
    """Return WAL on official fixed SQLite lines, otherwise DELETE."""
    if _is_wal_safe(sqlite3.sqlite_version_info):
        return "WAL"
    return "DELETE"


def upsert_document_row(
    connection: sqlite3.Connection, workspace_id: str, document: CatalogDocument
) -> None:
    """Write one catalog row on an open connection.

    Callers own the surrounding transaction.

    Args:
        connection (sqlite3.Connection): Open SQLite connection.
        workspace_id (str): Bound workspace for the row.
        document (CatalogDocument): Row to insert or replace.
    """
    connection.execute(
        _UPSERT_SQL,
        (
            workspace_id,
            document.reference.source_id,
            document.reference.source_type,
            document.file_name,
            document.title,
            document.content_format,
            document.status.value,
            document.uploaded_at.isoformat(),
            document.chunk_count,
            document.error,
            document.revision,
        ),
    )


def _is_wal_safe(version: tuple[int, ...]) -> bool:
    """Return whether this SQLite version matches an official WAL-reset fix.

    Official fixed lines are 3.51.3+, 3.50.7+ within 3.50, and 3.44.6+ within
    3.44. Unknown vendor backports are not treated as WAL-safe.
    """
    major = version[0] if len(version) > 0 else 0
    minor = version[1] if len(version) > 1 else 0
    patch = version[2] if len(version) > 2 else 0
    if major != 3:
        return False
    if minor > 51:
        return True
    if minor == 51:
        return patch >= 3
    if minor == 50:
        return patch >= 7
    if minor == 44:
        return patch >= 6
    return False
