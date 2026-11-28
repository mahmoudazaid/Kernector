"""SQLite store for MCP access profiles (#324).

Tables live in the catalog database (migration 007). ``workspace_id`` is bound
at construction. Auth/lifecycle paths use this store directly (no mocks).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from domain.mcp_access.models import McpAccessProfile, McpAccessProfileStatus
from domain.mcp_access.tokens import hash_access_token
from infrastructure.catalog import _connection
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_schema import apply_migrations
from infrastructure.catalog.workspace import require_workspace_id


class McpAccessProfileStoreError(RuntimeError):
    """SQLite access to MCP access-profile tables failed."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_expires(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    return datetime.fromisoformat(value)


def _is_expired(expires_at: str | None, *, now: datetime | None = None) -> bool:
    deadline = _parse_expires(expires_at)
    if deadline is None:
        return False
    clock = now or datetime.now(UTC)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return clock >= deadline


def _from_row(row: sqlite3.Row) -> McpAccessProfile:
    allowlist_raw = json.loads(row["allowlist"])
    keys = row.keys()
    description = row["description"] if "description" in keys else ""
    user_id = row["user_id"] if "user_id" in keys else None
    if isinstance(user_id, str) and not user_id.strip():
        user_id = None
    return McpAccessProfile(
        profile_id=row["profile_id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        name=row["name"],
        allowlist=frozenset(allowlist_raw),
        status=McpAccessProfileStatus(row["status"]),
        expires_at=row["expires_at"],
        token_hash=row["token_hash"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        description=description or "",
        disabled_at=row["disabled_at"],
        revoked_at=row["revoked_at"],
        user_id=user_id,
    )


class SqlMcpAccessProfileStore:
    """Workspace-bound MCP access-profile persistence."""

    def __init__(self, path: Path, workspace_id: str) -> None:
        self._workspace_id = require_workspace_id(workspace_id)
        self._path = path
        try:
            apply_migrations(path)
        except CatalogError as error:
            raise McpAccessProfileStoreError(
                f"could not apply MCP access-profile migrations at {path}"
            ) from error

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    def add(self, profile: McpAccessProfile) -> None:
        if profile.workspace_id != self._workspace_id:
            raise McpAccessProfileStoreError("workspace_id mismatch")
        with self._connect(write=True) as connection:
            try:
                if not profile.user_id or not str(profile.user_id).strip():
                    raise McpAccessProfileStoreError(
                        "user_id is required for new access profiles"
                    )
                connection.execute(
                    "INSERT INTO mcp_access_profiles ("
                    "workspace_id, profile_id, project_id, name, token_hash, "
                    "allowlist, status, expires_at, disabled_at, revoked_at, "
                    "created_at, updated_at, description, user_id"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self._workspace_id,
                        profile.profile_id,
                        profile.project_id,
                        profile.name,
                        profile.token_hash,
                        json.dumps(sorted(profile.allowlist)),
                        profile.status.value,
                        profile.expires_at,
                        profile.disabled_at,
                        profile.revoked_at,
                        profile.created_at,
                        profile.updated_at,
                        profile.description,
                        profile.user_id,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise McpAccessProfileStoreError(
                    "could not insert access profile"
                ) from error

    def get(self, profile_id: str) -> McpAccessProfile | None:
        with self._connect(write=False) as connection:
            row = connection.execute(
                "SELECT * FROM mcp_access_profiles "
                "WHERE workspace_id = ? AND profile_id = ?",
                (self._workspace_id, profile_id),
            ).fetchone()
        return None if row is None else _from_row(row)

    def list(self) -> tuple[McpAccessProfile, ...]:
        with self._connect(write=False) as connection:
            rows = connection.execute(
                "SELECT * FROM mcp_access_profiles "
                "WHERE workspace_id = ? ORDER BY created_at, profile_id",
                (self._workspace_id,),
            ).fetchall()
        return tuple(_from_row(row) for row in rows)

    def update(self, profile: McpAccessProfile) -> None:
        if profile.workspace_id != self._workspace_id:
            raise McpAccessProfileStoreError("workspace_id mismatch")
        with self._connect(write=True) as connection:
            cursor = connection.execute(
                "UPDATE mcp_access_profiles SET project_id = ?, name = ?, "
                "token_hash = ?, allowlist = ?, status = ?, expires_at = ?, "
                "disabled_at = ?, revoked_at = ?, updated_at = ?, description = ?, "
                "user_id = ? "
                "WHERE workspace_id = ? AND profile_id = ?",
                (
                    profile.project_id,
                    profile.name,
                    profile.token_hash,
                    json.dumps(sorted(profile.allowlist)),
                    profile.status.value,
                    profile.expires_at,
                    profile.disabled_at,
                    profile.revoked_at,
                    profile.updated_at,
                    profile.description,
                    profile.user_id,
                    self._workspace_id,
                    profile.profile_id,
                ),
            )
            if cursor.rowcount != 1:
                raise McpAccessProfileStoreError("access profile not found")

    def authenticate(self, plaintext_token: str) -> McpAccessProfile | None:
        token_hash = hash_access_token(plaintext_token)
        with self._connect(write=False) as connection:
            row = connection.execute(
                "SELECT * FROM mcp_access_profiles "
                "WHERE workspace_id = ? AND token_hash = ?",
                (self._workspace_id, token_hash),
            ).fetchone()
        if row is None:
            return None
        return _usable_profile(row)

    def project_exists(self, project_id: str) -> bool:
        with self._connect(write=False) as connection:
            row = connection.execute(
                "SELECT 1 FROM projects WHERE workspace_id = ? AND project_id = ?",
                (self._workspace_id, project_id),
            ).fetchone()
        return row is not None

    def _connect(self, *, write: bool):
        try:
            connection = _connection.connect(self._path)
        except sqlite3.Error as error:
            raise McpAccessProfileStoreError(
                f"could not open MCP access-profile store at {self._path}"
            ) from error
        connection.row_factory = sqlite3.Row
        begin = "BEGIN IMMEDIATE" if write else "BEGIN"

        class _Ctx:
            def __enter__(self_inner):
                try:
                    connection.execute(begin)
                    return connection
                except sqlite3.Error as error:
                    connection.close()
                    raise McpAccessProfileStoreError(
                        "could not begin MCP access-profile transaction"
                    ) from error

            def __exit__(self_inner, exc_type, exc, tb):
                try:
                    if exc_type is None:
                        connection.execute("COMMIT")
                    elif connection.in_transaction:
                        connection.execute("ROLLBACK")
                finally:
                    connection.close()
                return False

        return _Ctx()


def authenticate_access_token(
    path: Path, plaintext_token: str
) -> McpAccessProfile | None:
    """Resolve a profile bearer across workspaces (MCP middleware)."""
    try:
        apply_migrations(path)
        connection = _connection.connect(path)
    except (CatalogError, sqlite3.Error):
        return None
    connection.row_factory = sqlite3.Row
    try:
        token_hash = hash_access_token(plaintext_token)
        row = connection.execute(
            "SELECT * FROM mcp_access_profiles WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    if row is None:
        return None
    return _usable_profile(row)


def _usable_profile(row: sqlite3.Row) -> McpAccessProfile | None:
    profile = _from_row(row)
    if profile.status != McpAccessProfileStatus.ACTIVE:
        return None
    if _is_expired(profile.expires_at):
        return None
    return profile


def with_rotated_token(
    profile: McpAccessProfile, *, token_hash: str, updated_at: str
) -> McpAccessProfile:
    """Return *profile* with a new token hash (helper for rotate use case)."""
    return replace(profile, token_hash=token_hash, updated_at=updated_at)
