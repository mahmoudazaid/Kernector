"""SQLite adapter for namespaced versioned opaque workspace records."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from infrastructure.catalog import _connection
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_schema import apply_migrations
from infrastructure.catalog.workspace import require_workspace_id
from infrastructure.workspace_store.errors import (
    VersionedStoreConflictError,
    VersionedStoreError,
    VersionedStoreNotFoundError,
    VersionedStoreVersionConflictError,
)

_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_SELECT_COLUMNS = (
    "workspace_id, namespace, record_id, payload, version, created_at, updated_at"
)


@dataclass(frozen=True, slots=True)
class VersionedRecord:
    """One opaque versioned payload scoped by workspace and namespace."""

    workspace_id: str
    namespace: str
    record_id: str
    payload: str
    version: int
    created_at: datetime
    updated_at: datetime


class VersionedWorkspaceStore:
    """Persist opaque JSON payloads with integer CAS versions.

    Keys are ``(workspace_id, namespace, record_id)``. ``workspace_id`` is bound
    at construction; ``namespace`` is supplied by composition, never from HTTP.
    """

    def __init__(self, path: Path, workspace_id: str) -> None:
        self._workspace_id = require_workspace_id(workspace_id)
        self._path = path
        try:
            apply_migrations(path, migrations_dir=_MIGRATIONS)
        except CatalogError as error:
            raise VersionedStoreError(
                f"could not apply versioned store migrations at {path}"
            ) from error

    def create(self, namespace: str, record_id: str, payload: str) -> VersionedRecord:
        """Insert a new record at version 1.

        Raises:
            VersionedStoreConflictError: The key already exists.
            VersionedStoreError: SQLite access fails.
        """
        namespace = _require_key_part(namespace, "namespace")
        record_id = _require_key_part(record_id, "record_id")
        payload = _require_payload(payload)
        now = _utc_now()
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT 1 FROM versioned_workspace_records "
                    "WHERE workspace_id = ? AND namespace = ? AND record_id = ?",
                    (self._workspace_id, namespace, record_id),
                ).fetchone()
                if existing is not None:
                    connection.rollback()
                    raise VersionedStoreConflictError(
                        f"record already exists for namespace={namespace!r} "
                        f"record_id={record_id!r}"
                    )
                connection.execute(
                    "INSERT INTO versioned_workspace_records ("
                    "workspace_id, namespace, record_id, payload, version, "
                    "created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, 1, ?, ?)",
                    (
                        self._workspace_id,
                        namespace,
                        record_id,
                        payload,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                connection.commit()
            except VersionedStoreConflictError:
                raise
            except sqlite3.Error as error:
                connection.rollback()
                raise VersionedStoreError(
                    f"could not write versioned store at {self._path}"
                ) from error
            except Exception:
                connection.rollback()
                raise
        return VersionedRecord(
            workspace_id=self._workspace_id,
            namespace=namespace,
            record_id=record_id,
            payload=payload,
            version=1,
            created_at=now,
            updated_at=now,
        )

    def get(self, namespace: str, record_id: str) -> VersionedRecord | None:
        """Return the in-workspace namespaced record, or ``None``."""
        namespace = _require_key_part(namespace, "namespace")
        record_id = _require_key_part(record_id, "record_id")
        with self._connect() as connection:
            try:
                row = connection.execute(
                    f"SELECT {_SELECT_COLUMNS} FROM versioned_workspace_records "
                    "WHERE workspace_id = ? AND namespace = ? AND record_id = ?",
                    (self._workspace_id, namespace, record_id),
                ).fetchone()
            except sqlite3.Error as error:
                raise VersionedStoreError(
                    f"could not read versioned store at {self._path}"
                ) from error
        if row is None:
            return None
        return _record_from_row(row)

    def list_namespace(self, namespace: str) -> tuple[VersionedRecord, ...]:
        """Return every in-workspace record for ``namespace`` (stable by id)."""
        namespace = _require_key_part(namespace, "namespace")
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    f"SELECT {_SELECT_COLUMNS} FROM versioned_workspace_records "
                    "WHERE workspace_id = ? AND namespace = ? "
                    "ORDER BY record_id ASC",
                    (self._workspace_id, namespace),
                ).fetchall()
            except sqlite3.Error as error:
                raise VersionedStoreError(
                    f"could not list versioned store at {self._path}"
                ) from error
        return tuple(_record_from_row(row) for row in rows)

    def update(
        self,
        namespace: str,
        record_id: str,
        payload: str,
        *,
        expected_version: int,
    ) -> VersionedRecord:
        """Compare-and-swap update; success returns incremented version.

        Raises:
            VersionedStoreNotFoundError: No row for the key.
            VersionedStoreVersionConflictError: ``expected_version`` is stale.
            VersionedStoreError: SQLite access fails.
        """
        namespace = _require_key_part(namespace, "namespace")
        record_id = _require_key_part(record_id, "record_id")
        payload = _require_payload(payload)
        if not isinstance(expected_version, int) or isinstance(expected_version, bool):
            raise ValueError(
                "expected_version must be a positive integer, "
                f"got {type(expected_version).__name__}"
            )
        if expected_version <= 0:
            raise ValueError(
                f"expected_version must be a positive integer, got {expected_version}"
            )
        now = _utc_now()
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT version, created_at FROM versioned_workspace_records "
                    "WHERE workspace_id = ? AND namespace = ? AND record_id = ?",
                    (self._workspace_id, namespace, record_id),
                ).fetchone()
                if current is None:
                    connection.rollback()
                    raise VersionedStoreNotFoundError(
                        f"record not found for namespace={namespace!r} "
                        f"record_id={record_id!r}"
                    )
                if int(current["version"]) != expected_version:
                    connection.rollback()
                    raise VersionedStoreVersionConflictError(
                        "version conflict: "
                        f"expected {expected_version}, "
                        f"found {int(current['version'])}"
                    )
                connection.execute(
                    "UPDATE versioned_workspace_records "
                    "SET payload = ?, version = ?, updated_at = ? "
                    "WHERE workspace_id = ? AND namespace = ? AND record_id = ? "
                    "AND version = ?",
                    (
                        payload,
                        expected_version + 1,
                        now.isoformat(),
                        self._workspace_id,
                        namespace,
                        record_id,
                        expected_version,
                    ),
                )
                if connection.execute("SELECT changes()").fetchone()[0] != 1:
                    connection.rollback()
                    raise VersionedStoreVersionConflictError(
                        "version conflict during compare-and-swap"
                    )
                connection.commit()
                created_at = datetime.fromisoformat(str(current["created_at"]))
            except (
                VersionedStoreNotFoundError,
                VersionedStoreVersionConflictError,
            ):
                raise
            except sqlite3.Error as error:
                connection.rollback()
                raise VersionedStoreError(
                    f"could not write versioned store at {self._path}"
                ) from error
            except Exception:
                connection.rollback()
                raise
        return VersionedRecord(
            workspace_id=self._workspace_id,
            namespace=namespace,
            record_id=record_id,
            payload=payload,
            version=expected_version + 1,
            created_at=created_at,
            updated_at=now,
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = _connection.connect(self._path)
        except sqlite3.Error as error:
            raise VersionedStoreError(
                f"could not open versioned store at {self._path}"
            ) from error
        try:
            yield connection
        finally:
            connection.close()


def _require_key_part(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_payload(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"payload must be a string, got {type(value).__name__}")
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _record_from_row(row: sqlite3.Row) -> VersionedRecord:
    return VersionedRecord(
        workspace_id=str(row["workspace_id"]),
        namespace=str(row["namespace"]),
        record_id=str(row["record_id"]),
        payload=str(row["payload"]),
        version=int(row["version"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )
