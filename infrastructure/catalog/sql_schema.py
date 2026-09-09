"""Versioned SQLite schema for the SQL document catalog."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from infrastructure.catalog.errors import CatalogError

_MIGRATION_NAME = re.compile(r"^(\d+)_.+\.sql$")
_SHIPPED_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_BUSY_TIMEOUT_MS = 5000


def current_schema_version(path: Path) -> int:
    """Return the recorded schema version without creating a missing database.

    Args:
        path (Path): SQLite database path.

    Returns:
        int: Recorded version, or ``0`` when the file is missing or has no
            ``schema_version`` table.

    Raises:
        CatalogError: SQLite cannot read the existing database.
    """
    if not path.exists():
        return 0
    try:
        connection = sqlite3.connect(path)
        try:
            row = connection.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            return 0
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise CatalogError(f"could not read schema version at {path}") from error
    if row is None:
        return 0
    return int(row[0])


def apply_migrations(
    path: Path, *, migrations_dir: Path | None = None
) -> None:
    """Apply numbered SQL migration files in order.

    Each file and its ``schema_version`` update share one transaction. A
    failing file rolls back that schema version only.

    Args:
        path (Path): SQLite database path. Parent directories are created.
        migrations_dir (Path | None): Directory of numbered ``*.sql`` files.
            Defaults to the shipped catalog migrations.

    Raises:
        CatalogError: The database is at an unsupported future version, a
            migration file is invalid, or SQLite fails.
    """
    directory = migrations_dir or _SHIPPED_MIGRATIONS
    migrations = _load_migrations(directory)
    if not migrations:
        return
    latest = migrations[-1][0]
    recorded = current_schema_version(path)
    if recorded > latest:
        raise CatalogError(
            f"unsupported schema version {recorded}; latest shipped is {latest}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        connection = sqlite3.connect(path)
    except sqlite3.Error as error:
        raise CatalogError(f"could not open catalog database at {path}") from error
    try:
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        for version, sql in migrations:
            if version <= recorded:
                continue
            _apply_one(connection, version, sql)
    except CatalogError:
        raise
    except sqlite3.Error as error:
        raise CatalogError(f"could not apply catalog migrations at {path}") from error
    finally:
        connection.close()


def _load_migrations(directory: Path) -> list[tuple[int, str]]:
    loaded: list[tuple[int, str]] = []
    if not directory.is_dir():
        return loaded
    for file_path in sorted(directory.iterdir()):
        match = _MIGRATION_NAME.match(file_path.name)
        if match is None:
            continue
        loaded.append((int(match.group(1)), file_path.read_text(encoding="utf-8")))
    loaded.sort(key=lambda item: item[0])
    return loaded


def _apply_one(connection: sqlite3.Connection, version: int, sql: str) -> None:
    if connection.in_transaction:
        connection.rollback()
    script = f"BEGIN IMMEDIATE;\n{sql}"
    try:
        connection.executescript(script)
        connection.execute(
            "UPDATE schema_version SET version = ?",
            (version,),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
