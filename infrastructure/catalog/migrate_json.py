"""Import unscoped JSON catalog rows into a workspace-scoped SQLite catalog."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from infrastructure.catalog import _connection
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.json_catalog import JsonDocumentCatalog
from infrastructure.catalog.sql_schema import apply_migrations
from infrastructure.catalog.workspace import require_workspace_id


def migrate_json_catalog_to_sql(
    json_path: Path, sql_path: Path, workspace_id: str
) -> None:
    """Copy JSON catalog rows into SQLite for one workspace.

    Validates ``workspace_id`` before opening SQLite. Import writes run in one
    ``BEGIN IMMEDIATE`` transaction. The source JSON file is never modified.

    Args:
        json_path (Path): Existing JSON catalog path.
        sql_path (Path): Destination SQLite catalog path.
        workspace_id (str): Target workspace for imported rows.

    Raises:
        ValueError: ``workspace_id`` is absent or fails the charset or length
            contract.
        CatalogError: Schema migration or SQLite import fails.
    """
    parsed = require_workspace_id(workspace_id)
    documents = JsonDocumentCatalog(json_path).all()
    apply_migrations(sql_path)
    try:
        connection = _connection.connect(sql_path)
    except sqlite3.Error as error:
        raise CatalogError(
            f"could not open catalog database at {sql_path}"
        ) from error
    try:
        connection.execute("BEGIN IMMEDIATE")
        for document in documents:
            _connection.upsert_document_row(connection, parsed, document)
        connection.commit()
    except sqlite3.Error as error:
        connection.rollback()
        raise CatalogError(f"could not import catalog into {sql_path}") from error
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
