"""Seam tests for pre-traffic SQLite migrate + backup (#486)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from composition import load_runtime_settings
from composition.sqlite_migrate import (
    MigrateSqliteError,
    MigrateSqliteResult,
    backup_sqlite_file,
    run_sqlite_migrations,
)
from infrastructure.catalog.sql_schema import apply_migrations, current_schema_version
from infrastructure.config import Settings


def _settings_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    catalog = tmp_path / "catalog" / "catalog.sqlite"
    auth = tmp_path / "auth" / "auth.sqlite"
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", str(catalog))
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "local")
    monkeypatch.setenv("AUTH_SQL_PATH", str(auth))
    monkeypatch.setenv("CHROMA_PERSIST_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("DOCUMENT_UPLOAD_BLOB_PATH", str(tmp_path / "uploads"))
    return load_runtime_settings()


def test_run_sqlite_migrations_creates_fresh_schemas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings_for(tmp_path, monkeypatch)
    result = run_sqlite_migrations(settings, backup_root=tmp_path / "backups")

    assert isinstance(result, MigrateSqliteResult)
    assert result.catalog_path.exists()
    assert result.auth_path.exists()
    assert result.workspace_store_path.exists()
    assert result.feedback_path.exists()
    assert current_schema_version(result.catalog_path) >= 1
    assert current_schema_version(result.auth_path) >= 1
    assert result.backups == ()


def test_run_sqlite_migrations_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings_for(tmp_path, monkeypatch)
    first = run_sqlite_migrations(settings, backup_root=tmp_path / "backups")
    catalog_version = current_schema_version(first.catalog_path)
    auth_version = current_schema_version(first.auth_path)

    second = run_sqlite_migrations(settings, backup_root=tmp_path / "backups")

    assert current_schema_version(second.catalog_path) == catalog_version
    assert current_schema_version(second.auth_path) == auth_version


def test_run_sqlite_migrations_backs_up_existing_sqlite_before_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings_for(tmp_path, monkeypatch)
    catalog = settings.document_catalog.sql_path
    assert catalog is not None
    catalog.parent.mkdir(parents=True, exist_ok=True)
    apply_migrations(catalog)
    connection = sqlite3.connect(catalog)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS customer_marker (id INTEGER PRIMARY KEY)"
        )
        connection.execute("INSERT INTO customer_marker (id) VALUES (42)")
        connection.commit()
    finally:
        connection.close()

    result = run_sqlite_migrations(settings, backup_root=tmp_path / "backups")

    assert len(result.backups) >= 1
    backup = next(path for path in result.backups if path.name.startswith("catalog"))
    assert backup.exists()
    restored = sqlite3.connect(backup)
    try:
        row = restored.execute("SELECT id FROM customer_marker").fetchone()
    finally:
        restored.close()
    assert row == (42,)


def test_backup_sqlite_file_captures_wal_mode_data(tmp_path: Path) -> None:
    source = tmp_path / "db.sqlite"
    dest_dir = tmp_path / "backups"
    writer = sqlite3.connect(source)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY, note TEXT)")
        writer.execute("INSERT INTO marker (id, note) VALUES (1, 'from-wal')")
        writer.commit()
        # Keep the writer open so uncheckpointed WAL pages exist while
        # the online backup runs (mirrors api/mcp holding the DB open).
        copied = backup_sqlite_file(source, dest_dir, label="catalog")
    finally:
        writer.close()

    assert copied.exists()
    assert not (dest_dir / f"{copied.name}-wal").exists()
    restored = sqlite3.connect(copied)
    try:
        row = restored.execute("SELECT note FROM marker WHERE id = 1").fetchone()
    finally:
        restored.close()
    assert row == ("from-wal",)


def test_run_sqlite_migrations_preserves_original_when_migrate_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings_for(tmp_path, monkeypatch)
    catalog = settings.document_catalog.sql_path
    assert catalog is not None
    catalog.parent.mkdir(parents=True, exist_ok=True)
    apply_migrations(catalog)
    before = catalog.read_bytes()

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(
        "composition.sqlite_migrate.apply_migrations",
        boom,
    )

    with pytest.raises(MigrateSqliteError, match="simulated migration failure"):
        run_sqlite_migrations(settings, backup_root=tmp_path / "backups")

    assert catalog.read_bytes() == before
    assert any((tmp_path / "backups").iterdir())
