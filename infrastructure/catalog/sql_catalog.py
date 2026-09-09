"""SQLite adapter for the document catalog, bound to one workspace."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from domain.knowledge import CatalogDocument, CatalogStatus, SourceReference
from infrastructure.catalog import _connection
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_schema import apply_migrations
from infrastructure.catalog.workspace import require_workspace_id


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
        self._workspace_id = require_workspace_id(workspace_id)
        self._path = path
        apply_migrations(path)

    def all(self) -> Sequence[CatalogDocument]:
        """Return every catalog record for this workspace."""
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    f"SELECT {_connection.SELECT_COLUMNS} FROM catalog_documents "
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
                    f"SELECT {_connection.SELECT_COLUMNS} FROM catalog_documents "
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
                _connection.upsert_document_row(
                    connection, self._workspace_id, document
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
            connection = _connection.connect(self._path)
        except sqlite3.Error as error:
            raise CatalogError(
                f"could not open catalog database at {self._path}"
            ) from error
        try:
            yield connection
        finally:
            connection.close()


def _document_from_row(row: sqlite3.Row) -> CatalogDocument:
    title = row["title"]
    content_format = row["content_format"]
    error = row["error"]
    revision = row["revision"]
    return CatalogDocument(
        reference=SourceReference(str(row["source_id"]), str(row["source_type"])),
        file_name=str(row["file_name"]),
        title=None if title is None else str(title),
        content_format=None if content_format is None else str(content_format),
        status=CatalogStatus(str(row["status"])),
        uploaded_at=datetime.fromisoformat(str(row["uploaded_at"])),
        chunk_count=int(row["chunk_count"]),
        error=None if error is None else str(error),
        revision=None if revision is None else str(revision),
    )
