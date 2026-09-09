"""SQLite adapter for the document catalog, bound to one workspace."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from domain.knowledge import CatalogDocument, CatalogStatus, SourceReference
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_schema import apply_migrations
from infrastructure.catalog.workspace import parse_workspace_id

_BUSY_TIMEOUT_MS = 5000
_SELECT_COLUMNS = (
    "source_id, source_type, file_name, title, content_format, status, "
    "uploaded_at, chunk_count, error, revision"
)
_UPSERT_SQL = f"""
INSERT INTO catalog_documents (
    workspace_id, {_SELECT_COLUMNS}
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


class SqlDocumentCatalog:
    """Persist catalog rows in SQLite, isolated to one workspace.

    Each method opens its own connection. Writes take ``BEGIN IMMEDIATE`` and a
    bounded busy timeout. ``workspace_id`` is bound as a query parameter.

    Args:
        path (Path): SQLite database path. Parent directories are created after
            ``workspace_id`` validation.
        workspace_id (str): Case-sensitive workspace this adapter may see.

    Raises:
        ValueError: ``workspace_id`` is absent or fails the charset/length
            contract.
        CatalogError: Schema migration or SQLite access fails.
    """

    def __init__(self, path: Path, workspace_id: str) -> None:
        parsed = parse_workspace_id(workspace_id)
        if parsed is None:
            raise ValueError(
                "workspace_id must fullmatch [A-Za-z0-9_-]+ and be at most "
                "64 characters"
            )
        self._workspace_id = parsed
        self._path = path
        apply_migrations(path)

    def all(self) -> Sequence[CatalogDocument]:
        """Return every catalog record for this workspace."""
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    f"SELECT {_SELECT_COLUMNS} FROM catalog_documents "
                    "WHERE workspace_id = ?",
                    (self._workspace_id,),
                ).fetchall()
            except sqlite3.Error as error:
                raise CatalogError(
                    f"could not read catalog at {self._path}"
                ) from error
        return tuple(_document_from_row(row) for row in rows)

    def get(self, reference: SourceReference) -> CatalogDocument | None:
        """Return the in-workspace record for ``reference``, or ``None``."""
        with self._connect() as connection:
            try:
                row = connection.execute(
                    f"SELECT {_SELECT_COLUMNS} FROM catalog_documents "
                    "WHERE workspace_id = ? AND source_type = ? AND source_id = ?",
                    (self._workspace_id, reference.source_type, reference.source_id),
                ).fetchone()
            except sqlite3.Error as error:
                raise CatalogError(
                    f"could not read catalog at {self._path}"
                ) from error
        if row is None:
            return None
        return _document_from_row(row)

    def upsert(self, document: CatalogDocument) -> None:
        """Insert or replace the in-workspace record for ``document.reference``."""
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                _upsert_document_row(connection, self._workspace_id, document)
                connection.commit()
            except sqlite3.Error as error:
                connection.rollback()
                raise CatalogError(
                    f"could not write catalog at {self._path}"
                ) from error
            except Exception:
                connection.rollback()
                raise

    def delete(self, reference: SourceReference) -> None:
        """Remove the in-workspace record. Missing references are a no-op."""
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM catalog_documents "
                    "WHERE workspace_id = ? AND source_type = ? AND source_id = ?",
                    (self._workspace_id, reference.source_type, reference.source_id),
                )
                connection.commit()
            except sqlite3.Error as error:
                connection.rollback()
                raise CatalogError(
                    f"could not write catalog at {self._path}"
                ) from error
            except Exception:
                connection.rollback()
                raise

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self._path, isolation_level=None)
        except sqlite3.Error as error:
            raise CatalogError(
                f"could not open catalog database at {self._path}"
            ) from error
        try:
            connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
            connection.execute(f"PRAGMA journal_mode = {_journal_mode()}")
            yield connection
        except sqlite3.Error as error:
            raise CatalogError(
                f"could not configure catalog database at {self._path}"
            ) from error
        finally:
            connection.close()


def _upsert_document_row(
    connection: sqlite3.Connection, workspace_id: str, document: CatalogDocument
) -> None:
    """Write one catalog row on an open connection.

    Callers own the surrounding transaction. Used by the SQL catalog and the
    JSON-to-SQL importer.

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


def _journal_mode() -> str:
    if _is_wal_safe(sqlite3.sqlite_version_info):
        return "WAL"
    return "DELETE"


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


def _document_from_row(row: tuple[object, ...]) -> CatalogDocument:
    (
        source_id,
        source_type,
        file_name,
        title,
        content_format,
        status,
        uploaded_at,
        chunk_count,
        error,
        revision,
    ) = row
    return CatalogDocument(
        reference=SourceReference(str(source_id), str(source_type)),
        file_name=str(file_name),
        title=None if title is None else str(title),
        content_format=None if content_format is None else str(content_format),
        status=CatalogStatus(str(status)),
        uploaded_at=datetime.fromisoformat(str(uploaded_at)),
        chunk_count=int(chunk_count),  # type: ignore[arg-type]
        error=None if error is None else str(error),
        revision=None if revision is None else str(revision),
    )
