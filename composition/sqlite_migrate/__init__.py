"""Pre-traffic SQLite migrate with optional file backups (#486).

Compose runs this oneshot before API/MCP traffic. Store constructors still
call ``apply_migrations`` idempotently on open; this entrypoint fails the
dependency chain early and keeps a practical pre-migrate copy of existing
SQLite files.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from application.errors import ConfigurationError
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_schema import apply_migrations, current_schema_version
from infrastructure.config import Settings

_INFRA = Path(__file__).resolve().parents[2] / "infrastructure"
_CATALOG_MIGRATIONS = _INFRA / "catalog" / "migrations"
_AUTH_MIGRATIONS = _INFRA / "auth" / "migrations"
_FEEDBACK_MIGRATIONS = _INFRA / "feedback" / "migrations"
_WORKSPACE_STORE_MIGRATIONS = _INFRA / "workspace_store" / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d+)_.+\.sql$")
_DEFAULT_BACKUP_KEEP = 5


class MigrateSqliteError(RuntimeError):
    """SQLite pre-migrate backup or schema apply failed."""


@dataclass(frozen=True, slots=True)
class MigrateSqliteResult:
    """Paths touched by a successful migrate run."""

    catalog_path: Path
    auth_path: Path
    workspace_store_path: Path
    feedback_path: Path
    backups: tuple[Path, ...]


def backup_sqlite_file(source: Path, dest_dir: Path, *, label: str) -> Path:
    """Take a consistent online backup of ``source`` into ``dest_dir``.

    Uses SQLite's backup API so concurrent writers and WAL sidecars are
    handled without torn file copies.

    Args:
        source: Existing SQLite database file.
        dest_dir: Directory that receives the backup file.
        label: Short name embedded in the backup filename.

    Returns:
        Path: Copied main database file under ``dest_dir``.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = dest_dir / f"{label}-{stamp}.sqlite"
    source_conn = sqlite3.connect(source)
    try:
        dest_conn = sqlite3.connect(dest)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()
    return dest


def prune_sqlite_backups(
    dest_dir: Path, *, label: str, keep: int = _DEFAULT_BACKUP_KEEP
) -> tuple[Path, ...]:
    """Delete older ``{label}-*.sqlite`` backups, keeping the newest ``keep``.

    Args:
        dest_dir: Backup directory.
        label: Backup label prefix (for example ``catalog``).
        keep: Number of newest backups to retain. ``0`` deletes all.

    Returns:
        tuple[Path, ...]: Paths that were deleted.
    """
    if keep < 0:
        raise ValueError("keep must be >= 0")
    if not dest_dir.is_dir():
        return ()
    matches = sorted(
        (
            path
            for path in dest_dir.glob(f"{label}-*.sqlite")
            if path.is_file()
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    deleted: list[Path] = []
    for path in matches[keep:]:
        path.unlink(missing_ok=True)
        deleted.append(path)
    return tuple(deleted)


def _latest_shipped_version(migrations_dir: Path) -> int:
    latest = 0
    if not migrations_dir.is_dir():
        return latest
    for file_path in migrations_dir.iterdir():
        match = _MIGRATION_NAME.match(file_path.name)
        if match is None:
            continue
        latest = max(latest, int(match.group(1)))
    return latest


def _migration_pending(path: Path, migrations_dir: Path) -> bool:
    """Return True when ``path`` exists and is behind shipped migrations."""
    if not path.exists():
        return False
    return current_schema_version(path) < _latest_shipped_version(migrations_dir)


def _workspace_store_path(settings: Settings) -> Path:
    store_path = Path("data/workspace_store/workspace.sqlite")
    if settings.document_catalog.sql_path is not None:
        store_path = (
            settings.document_catalog.sql_path.parent / "workspace_store.sqlite"
        )
    return store_path


def _feedback_path(settings: Settings) -> Path:
    store_path = Path("data/feedback/response_feedback.sqlite")
    if settings.document_catalog.sql_path is not None:
        store_path = (
            settings.document_catalog.sql_path.parent / "response_feedback.sqlite"
        )
    return store_path


def run_sqlite_migrations(
    settings: Settings,
    *,
    backup_root: Path | None = None,
    keep: int = _DEFAULT_BACKUP_KEEP,
) -> MigrateSqliteResult:
    """Back up pending SQLite files then apply all migrations.

    Backups run only when a database exists and is behind the shipped
    migrations for that store. After a successful run, only the newest
    ``keep`` backups per label are retained under ``backup_root``.

    Args:
        settings: Runtime settings with catalog and auth paths.
        backup_root: Directory for pre-migrate copies. Defaults to
            ``<catalog-parent>/backups``.
        keep: Newest backups to retain per label after a successful run
            (default ``5``).

    Returns:
        MigrateSqliteResult: Resolved database paths and backup files created.

    Raises:
        ConfigurationError: Required catalog path is missing.
        MigrateSqliteError: Backup or migration failed. Existing DB bytes are
            left untouched when ``apply_migrations`` raises after backup.
    """
    catalog_path = settings.document_catalog.sql_path
    if catalog_path is None:
        raise ConfigurationError(
            "DOCUMENT_CATALOG_SQL_PATH is blank; unset it to use the "
            "data/catalog/catalog.sqlite default"
        )
    auth_path = settings.auth.sql_path
    workspace_path = _workspace_store_path(settings)
    feedback_path = _feedback_path(settings)

    if backup_root is None:
        backup_root = catalog_path.parent / "backups"

    backups: list[Path] = []
    targets = (
        ("catalog", catalog_path, _CATALOG_MIGRATIONS),
        ("auth", auth_path, _AUTH_MIGRATIONS),
        ("workspace_store", workspace_path, _WORKSPACE_STORE_MIGRATIONS),
        ("feedback", feedback_path, _FEEDBACK_MIGRATIONS),
    )
    for label, path, migrations_dir in targets:
        try:
            if not _migration_pending(path, migrations_dir):
                continue
            backups.append(backup_sqlite_file(path, backup_root, label=label))
        except (OSError, sqlite3.Error, CatalogError) as error:
            raise MigrateSqliteError(
                f"could not back up {path}: {error}"
            ) from error

    try:
        apply_migrations(catalog_path)
        apply_migrations(auth_path, migrations_dir=_AUTH_MIGRATIONS)
        apply_migrations(workspace_path, migrations_dir=_WORKSPACE_STORE_MIGRATIONS)
        apply_migrations(feedback_path, migrations_dir=_FEEDBACK_MIGRATIONS)
    except (CatalogError, OSError, RuntimeError) as error:
        raise MigrateSqliteError(str(error)) from error

    for label, _path, _migrations_dir in targets:
        prune_sqlite_backups(backup_root, label=label, keep=keep)

    return MigrateSqliteResult(
        catalog_path=catalog_path,
        auth_path=auth_path,
        workspace_store_path=workspace_path,
        feedback_path=feedback_path,
        backups=tuple(backups),
    )
