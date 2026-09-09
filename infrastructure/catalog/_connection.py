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
_COLUMN_NAMES = tuple(part.strip() for part in SELECT_COLUMNS.split(","))
_CONFLICT_KEY = ("workspace_id", "source_type", "source_id")
_UPDATABLE_COLUMNS = tuple(name for name in _COLUMN_NAMES if name not in _CONFLICT_KEY)
_UPSERT_SQL = f"""
INSERT INTO catalog_documents (
    workspace_id, {SELECT_COLUMNS}
) VALUES (
    :workspace_id, {", ".join(f":{name}" for name in _COLUMN_NAMES)}
)
ON CONFLICT ({", ".join(_CONFLICT_KEY)}) DO UPDATE SET
    {", ".join(f"{name} = excluded.{name}" for name in _UPDATABLE_COLUMNS)}
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
        set_journal_mode(connection)
    except Exception:
        connection.close()
        raise
    return connection


def journal_mode() -> str:
    """Return WAL on official fixed SQLite lines, otherwise DELETE."""
    if _is_wal_safe(sqlite3.sqlite_version_info):
        return "WAL"
    return "DELETE"


def set_journal_mode(connection: sqlite3.Connection) -> None:
    """Apply the journal mode, tolerating a concurrent transition.

    The rollback-to-WAL transition needs an exclusive lock and returns
    SQLITE_BUSY immediately instead of waiting on ``busy_timeout``. Journal
    mode is a persistent database property, so whichever cold-start writer
    wins the race sets it for every later connection. The match uses the
    primary result code (``sqlite_errorcode & 0xFF``) so extended BUSY and
    LOCKED variants are covered.

    Args:
        connection (sqlite3.Connection): Open SQLite connection.

    Raises:
        sqlite3.OperationalError: The PRAGMA failed for a reason other than
            a concurrent journal-mode transition.
    """
    try:
        connection.execute(f"PRAGMA journal_mode = {journal_mode()}")
    except sqlite3.OperationalError as error:
        if error.sqlite_errorcode & 0xFF not in (
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
        ):
            raise


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
        {
            "workspace_id": workspace_id,
            "source_id": document.reference.source_id,
            "source_type": document.reference.source_type,
            "file_name": document.file_name,
            "title": document.title,
            "content_format": document.content_format,
            "status": document.status.value,
            "uploaded_at": document.uploaded_at.isoformat(),
            "chunk_count": document.chunk_count,
            "error": document.error,
            "revision": document.revision,
        },
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
