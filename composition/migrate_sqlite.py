"""Pre-traffic SQLite migrate with optional file backups (#486).

Compose runs this oneshot before API/MCP traffic. Store constructors still
call ``apply_migrations`` idempotently on open; this entrypoint fails the
dependency chain early and keeps a practical pre-migrate copy of existing
SQLite files.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from application.errors import ConfigurationError
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_schema import apply_migrations
from infrastructure.config import Settings

_INFRA = Path(__file__).resolve().parents[1] / "infrastructure"
_AUTH_MIGRATIONS = _INFRA / "auth" / "migrations"
_FEEDBACK_MIGRATIONS = _INFRA / "feedback" / "migrations"
_WORKSPACE_STORE_MIGRATIONS = _INFRA / "workspace_store" / "migrations"


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
    """Copy ``source`` (and WAL/SHM sidecars when present) into ``dest_dir``.

    Args:
        source: Existing SQLite database file.
        dest_dir: Directory that receives the backup files.
        label: Short name embedded in the backup filename.

    Returns:
        Path: Copied main database file under ``dest_dir``.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = dest_dir / f"{label}-{stamp}.sqlite"
    shutil.copy2(source, dest)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{source}{suffix}")
        if sidecar.exists():
            shutil.copy2(sidecar, dest_dir / f"{dest.name}{suffix}")
    return dest


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
) -> MigrateSqliteResult:
    """Back up existing SQLite files (when present) then apply all migrations.

    Args:
        settings: Runtime settings with catalog and auth paths.
        backup_root: Directory for pre-migrate copies. Defaults to
            ``<catalog-parent>/backups``.

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
        ("catalog", catalog_path),
        ("auth", auth_path),
        ("workspace_store", workspace_path),
        ("feedback", feedback_path),
    )
    for label, path in targets:
        if path.exists():
            try:
                backups.append(
                    backup_sqlite_file(path, backup_root, label=label)
                )
            except OSError as error:
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

    return MigrateSqliteResult(
        catalog_path=catalog_path,
        auth_path=auth_path,
        workspace_store_path=workspace_path,
        feedback_path=feedback_path,
        backups=tuple(backups),
    )
