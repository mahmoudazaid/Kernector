"""Tests for JSON to SQL catalog import."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceReference,
    SourceType,
)
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.json_catalog import JsonDocumentCatalog
from infrastructure.catalog.migrate_json import migrate_json_catalog_to_sql
from infrastructure.catalog import _connection as connection_module
from infrastructure.catalog.sql_catalog import SqlDocumentCatalog
from infrastructure.catalog.sql_schema import current_schema_version


def _document(
    *,
    source_id: str = "id-1",
    source_type: str = SourceType.KNOWLEDGE_DOCUMENT,
    file_name: str = "guide.md",
    title: str | None = "Guide",
    content_format: str | None = "markdown",
    status: CatalogStatus = CatalogStatus.READY,
    chunk_count: int = 2,
    error: str | None = None,
    revision: str | None = "rev-1",
) -> CatalogDocument:
    return CatalogDocument(
        reference=SourceReference(source_id, source_type),
        file_name=file_name,
        title=title,
        content_format=content_format,
        status=status,
        uploaded_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        chunk_count=chunk_count,
        error=error,
        revision=revision,
    )


def test_import_preserves_every_catalog_field(tmp_path: Path) -> None:
    json_path = tmp_path / "uploads.json"
    sql_path = tmp_path / "catalog.sqlite"
    document = _document(
        status=CatalogStatus.DEGRADED,
        chunk_count=0,
        error="upsert failed",
        revision="42",
        title="Guide",
        content_format="markdown",
    )
    JsonDocumentCatalog(json_path).upsert(document)
    original = json_path.read_bytes()

    migrate_json_catalog_to_sql(json_path, sql_path, "ws-a")

    assert json_path.read_bytes() == original
    assert SqlDocumentCatalog(sql_path, "ws-a").all() == (document,)


def test_rerun_is_idempotent_and_leaves_json_bytes_unchanged(
    tmp_path: Path,
) -> None:
    json_path = tmp_path / "uploads.json"
    sql_path = tmp_path / "catalog.sqlite"
    JsonDocumentCatalog(json_path).upsert(_document())
    original = json_path.read_bytes()
    migrate_json_catalog_to_sql(json_path, sql_path, "ws-a")
    migrate_json_catalog_to_sql(json_path, sql_path, "ws-a")
    assert json_path.read_bytes() == original
    assert SqlDocumentCatalog(sql_path, "ws-a").all() == (_document(),)


def test_invalid_workspace_id_does_no_database_work(tmp_path: Path) -> None:
    json_path = tmp_path / "uploads.json"
    sql_path = tmp_path / "missing" / "catalog.sqlite"
    JsonDocumentCatalog(json_path).upsert(_document())
    with pytest.raises(ValueError, match="workspace_id"):
        migrate_json_catalog_to_sql(json_path, sql_path, "bad id")
    assert not sql_path.exists()
    assert current_schema_version(sql_path) == 0


def test_import_into_workspace_a_does_not_mutate_workspace_b(
    tmp_path: Path,
) -> None:
    json_path = tmp_path / "uploads.json"
    sql_path = tmp_path / "catalog.sqlite"
    existing_b = _document(
        file_name="b.md",
        title="Workspace B",
        chunk_count=9,
        revision="b-rev",
        error=None,
    )
    SqlDocumentCatalog(sql_path, "ws-b").upsert(existing_b)
    imported = _document(file_name="a.md", title="Workspace A", chunk_count=1)
    JsonDocumentCatalog(json_path).upsert(imported)

    migrate_json_catalog_to_sql(json_path, sql_path, "ws-a")

    assert SqlDocumentCatalog(sql_path, "ws-b").all() == (existing_b,)
    assert SqlDocumentCatalog(sql_path, "ws-a").all() == (imported,)


def test_import_failure_rolls_back_rows_and_leaves_json_bytes_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    json_path = tmp_path / "uploads.json"
    sql_path = tmp_path / "catalog.sqlite"
    preexisting = _document(source_id="id-existing", file_name="old.md", chunk_count=3)
    SqlDocumentCatalog(sql_path, "ws-a").upsert(preexisting)
    JsonDocumentCatalog(json_path).upsert(_document(source_id="id-new", file_name="new.md"))
    original = json_path.read_bytes()

    fail_writes = True
    real_connect = connection_module.connect

    class _FailingConnection:
        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner

        def execute(self, sql: str, parameters: object = ()) -> sqlite3.Cursor:
            if fail_writes and "INSERT" in sql.upper():
                raise sqlite3.OperationalError("injected import failure")
            return self._inner.execute(sql, parameters)

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    monkeypatch.setattr(
        connection_module,
        "connect",
        lambda *args, **kwargs: _FailingConnection(real_connect(*args, **kwargs)),
    )

    with pytest.raises(CatalogError) as raised:
        migrate_json_catalog_to_sql(json_path, sql_path, "ws-a")
    assert isinstance(raised.value.__cause__, sqlite3.Error)

    fail_writes = False
    monkeypatch.undo()
    assert json_path.read_bytes() == original
    catalog = SqlDocumentCatalog(sql_path, "ws-a")
    assert catalog.all() == (preexisting,)
    assert catalog.get(_document(source_id="id-new").reference) is None
    assert current_schema_version(sql_path) == 1
