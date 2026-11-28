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
    prune_sqlite_backups,
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
    backup_root = tmp_path / "backups"
    first = run_sqlite_migrations(settings, backup_root=backup_root)
    catalog_version = current_schema_version(first.catalog_path)
    auth_version = current_schema_version(first.auth_path)

    second = run_sqlite_migrations(settings, backup_root=backup_root)

    assert current_schema_version(second.catalog_path) == catalog_version
    assert current_schema_version(second.auth_path) == auth_version
    assert second.backups == ()
    assert not backup_root.exists() or list(backup_root.glob("*.sqlite")) == []


def test_run_sqlite_migrations_backs_up_existing_sqlite_before_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings_for(tmp_path, monkeypatch)
    catalog = settings.document_catalog.sql_path
    assert catalog is not None
    catalog.parent.mkdir(parents=True, exist_ok=True)
    # Pre-existing DB behind shipped migrations so a backup is required.
    connection = sqlite3.connect(catalog)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS customer_marker (id INTEGER PRIMARY KEY)"
        )
        connection.execute("INSERT INTO customer_marker (id) VALUES (42)")
        connection.commit()
    finally:
        connection.close()
    assert current_schema_version(catalog) == 0

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
    connection = sqlite3.connect(catalog)
    try:
        connection.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO marker (id) VALUES (7)")
        connection.commit()
    finally:
        connection.close()
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


def test_run_sqlite_migrations_skips_backup_when_already_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings_for(tmp_path, monkeypatch)
    backup_root = tmp_path / "backups"
    run_sqlite_migrations(settings, backup_root=backup_root)

    result = run_sqlite_migrations(settings, backup_root=backup_root)

    assert result.backups == ()
    assert not backup_root.exists() or list(backup_root.glob("*.sqlite")) == []


def test_prune_sqlite_backups_keeps_newest_n(tmp_path: Path) -> None:
    dest = tmp_path / "backups"
    dest.mkdir()
    for stamp in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z"):
        (dest / f"catalog-{stamp}.sqlite").write_bytes(b"x")

    deleted = prune_sqlite_backups(dest, label="catalog", keep=2)

    remaining = sorted(path.name for path in dest.glob("catalog-*.sqlite"))
    assert remaining == [
        "catalog-20260102T000000Z.sqlite",
        "catalog-20260103T000000Z.sqlite",
    ]
    assert [path.name for path in deleted] == ["catalog-20260101T000000Z.sqlite"]


def test_run_sqlite_migrations_prunes_old_backups_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings_for(tmp_path, monkeypatch)
    catalog = settings.document_catalog.sql_path
    assert catalog is not None
    catalog.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(catalog)
    try:
        connection.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
        connection.commit()
    finally:
        connection.close()
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    for stamp in ("20250101T000000Z", "20250102T000000Z"):
        (backup_root / f"catalog-{stamp}.sqlite").write_bytes(b"old")

    run_sqlite_migrations(settings, backup_root=backup_root, keep=2)

    remaining = sorted(path.name for path in backup_root.glob("catalog-*.sqlite"))
    assert len(remaining) == 2
    assert "catalog-20250101T000000Z.sqlite" not in remaining
