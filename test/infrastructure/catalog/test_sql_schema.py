"""Tests for SQLite catalog schema versioning and migrations."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading

import pytest

from infrastructure.catalog._connection import journal_mode
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_schema import apply_migrations, current_schema_version


def test_missing_database_reports_version_zero_without_creating_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing" / "catalog.sqlite"
    assert current_schema_version(path) == 0
    assert not path.exists()
    assert not path.parent.exists()


def test_apply_shipped_migration_advances_to_version_three(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    apply_migrations(path)
    assert current_schema_version(path) == 3
    assert path.is_file()


def test_legacy_uploaded_at_backfills_created_and_updated_then_drops_column(
    tmp_path: Path,
) -> None:
    """v2 rows with uploaded_at become equal created_at/updated_at; column gone."""
    from datetime import UTC, datetime

    from domain.knowledge import (
        CatalogDocument,
        CatalogStatus,
        SourceReference,
        SourceType,
    )
    from infrastructure.catalog.sql_catalog import SqlDocumentCatalog

    shipped_dir = (
        Path(__file__).resolve().parents[3]
        / "infrastructure"
        / "catalog"
        / "migrations"
    )
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for name in ("001_catalog_documents.sql", "002_catalog_connector_id.sql"):
        (migrations / name).write_text(
            (shipped_dir / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    path = tmp_path / "catalog.sqlite"
    apply_migrations(path, migrations_dir=migrations)
    assert current_schema_version(path) == 2

    stamp = "2026-08-28T12:00:00+00:00"
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO catalog_documents ("
            "workspace_id, source_id, source_type, file_name, title, "
            "content_format, status, uploaded_at, chunk_count, error, "
            "revision, connector_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ws-a",
                "legacy-1",
                "knowledge_document",
                "guide.md",
                "Guide",
                "markdown",
                "ready",
                stamp,
                2,
                None,
                None,
                None,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    apply_migrations(path)
    assert current_schema_version(path) == 3

    connection = sqlite3.connect(path)
    try:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(catalog_documents)")
        }
    finally:
        connection.close()
    assert "uploaded_at" not in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    catalog = SqlDocumentCatalog(path, "ws-a")
    document = catalog.get(
        SourceReference("legacy-1", SourceType.KNOWLEDGE_DOCUMENT)
    )
    assert document is not None
    expected = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    assert document.created_at == expected
    assert document.updated_at == expected
    assert document == CatalogDocument(
        reference=SourceReference("legacy-1", SourceType.KNOWLEDGE_DOCUMENT),
        file_name="guide.md",
        title="Guide",
        content_format="markdown",
        status=CatalogStatus.READY,
        created_at=expected,
        updated_at=expected,
        chunk_count=2,
        error=None,
    )


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


def test_failing_second_migration_rolls_back_and_keeps_prior_catalog(
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

    shipped_dir = (
        Path(__file__).resolve().parents[3]
        / "infrastructure"
        / "catalog"
        / "migrations"
    )
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for name in ("001_catalog_documents.sql", "002_catalog_connector_id.sql"):
        (migrations / name).write_text(
            (shipped_dir / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (migrations / "003_rename_then_fail.sql").write_text(
        "ALTER TABLE catalog_documents RENAME TO catalog_documents_renamed;\n"
        "THIS IS NOT VALID SQL;\n",
        encoding="utf-8",
    )
    path = tmp_path / "catalog.sqlite"
    with pytest.raises(CatalogError):
        apply_migrations(path, migrations_dir=migrations)
    assert current_schema_version(path) == 2

    catalog = SqlDocumentCatalog(path, "ws-a")
    document = CatalogDocument(
        reference=SourceReference("id-v1", SourceType.KNOWLEDGE_DOCUMENT),
        file_name="guide.md",
        title="Guide",
        content_format="markdown",
        status=CatalogStatus.READY,
        created_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        chunk_count=2,
        error=None,
        revision="1",
        connector_id="connector-a",
    )
    catalog.upsert(document)
    assert catalog.get(document.reference) == document
    assert catalog.all() == (document,)


def test_concurrent_first_apply_migrations_converge(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    workers = 6
    barrier = threading.Barrier(workers)

    def migrate() -> None:
        barrier.wait(timeout=5)
        apply_migrations(path)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(migrate) for _ in range(workers)]
        for future in futures:
            future.result(timeout=15)

    assert current_schema_version(path) == 3
    connection = sqlite3.connect(path)
    try:
        recorded_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        connection.close()
    assert str(recorded_mode).lower() == journal_mode().lower()
    from infrastructure.catalog.sql_catalog import SqlDocumentCatalog

    catalog = SqlDocumentCatalog(path, "ws-a")
    assert catalog.all() == ()


def test_set_journal_mode_tolerates_locked_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infrastructure.catalog._connection import set_journal_mode

    monkeypatch.setattr(
        "infrastructure.catalog._connection.journal_mode", lambda: "WAL"
    )
    path = tmp_path / "busy.sqlite"
    bootstrap = sqlite3.connect(path)
    bootstrap.execute("CREATE TABLE t (x)")
    bootstrap.close()
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN")
    holder.execute("SELECT * FROM t").fetchall()
    victim = sqlite3.connect(path, isolation_level=None)
    victim.execute("PRAGMA busy_timeout = 100")
    try:
        with pytest.raises(sqlite3.OperationalError) as raised:
            victim.execute("PRAGMA journal_mode = WAL")
        assert raised.value.sqlite_errorname == "SQLITE_BUSY"
        set_journal_mode(victim)
    finally:
        holder.rollback()
        holder.close()
        victim.close()


def test_set_journal_mode_reraises_non_busy_operational_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infrastructure.catalog._connection import set_journal_mode

    monkeypatch.setattr(
        "infrastructure.catalog._connection.journal_mode", lambda: "WAL"
    )
    path = tmp_path / "readonly.sqlite"
    bootstrap = sqlite3.connect(path)
    bootstrap.execute("CREATE TABLE t (x)")
    bootstrap.close()
    victim = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError) as raised:
            set_journal_mode(victim)
        assert raised.value.sqlite_errorcode & 0xFF == sqlite3.SQLITE_READONLY
    finally:
        victim.close()


def test_non_sqlite_file_reports_catalog_error_not_version_zero(
    tmp_path: Path,
) -> None:
    path = tmp_path / "uploads.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(CatalogError):
        current_schema_version(path)
    with pytest.raises(CatalogError):
        apply_migrations(path)
