"""Tests for SQLite catalog schema versioning and migrations."""

from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_schema import apply_migrations, current_schema_version


def test_missing_database_reports_version_zero_without_creating_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing" / "catalog.sqlite"
    assert current_schema_version(path) == 0
    assert not path.exists()
    assert not path.parent.exists()


def test_apply_shipped_migration_advances_to_version_one(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    apply_migrations(path)
    assert current_schema_version(path) == 1
    assert path.is_file()


def test_unsupported_future_schema_version_is_rejected(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "catalog.sqlite"
    apply_migrations(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("UPDATE schema_version SET version = 99")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(CatalogError, match="unsupported"):
        apply_migrations(path)
    assert current_schema_version(path) == 99


def test_sqlite_error_during_migration_is_catalog_error(
    tmp_path: Path,
) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_broken.sql").write_text(
        "CREATE TABLE catalog_documents (id INTEGER);\nTHIS IS NOT SQL;\n",
        encoding="utf-8",
    )
    path = tmp_path / "catalog.sqlite"

    with pytest.raises(CatalogError) as raised:
        apply_migrations(path, migrations_dir=migrations)

    assert raised.value.__cause__ is not None
    assert current_schema_version(path) == 0


def test_failing_second_migration_rolls_back_and_keeps_v1_catalog(
    tmp_path: Path,
) -> None:
    from infrastructure.catalog.sql_catalog import SqlDocumentCatalog
    from domain.knowledge import (
        CatalogDocument,
        CatalogStatus,
        SourceReference,
        SourceType,
    )
    from datetime import UTC, datetime

    shipped = (
        Path(__file__).resolve().parents[3]
        / "infrastructure"
        / "catalog"
        / "migrations"
        / "001_catalog_documents.sql"
    )
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_catalog_documents.sql").write_text(
        shipped.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (migrations / "002_rename_then_fail.sql").write_text(
        "ALTER TABLE catalog_documents RENAME TO catalog_documents_renamed;\n"
        "THIS IS NOT VALID SQL;\n",
        encoding="utf-8",
    )
    path = tmp_path / "catalog.sqlite"
    with pytest.raises(CatalogError):
        apply_migrations(path, migrations_dir=migrations)
    assert current_schema_version(path) == 1

    catalog = SqlDocumentCatalog(path, "ws-a")
    document = CatalogDocument(
        reference=SourceReference("id-v1", SourceType.KNOWLEDGE_DOCUMENT),
        file_name="guide.md",
        title="Guide",
        content_format="markdown",
        status=CatalogStatus.READY,
        uploaded_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        chunk_count=2,
        error=None,
        revision="1",
    )
    catalog.upsert(document)
    assert catalog.get(document.reference) == document
    assert catalog.all() == (document,)
