"""SQLite store for local users, sessions, preferences, and membership (#182, #446)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from domain.auth.models import (
    MEMBER_ROLE,
    LoginAttemptState,
    ProjectGrant,
    StoredPreferences,
    StoredSession,
    StoredUser,
    WorkspaceMembership,
)
from domain.auth.passwords import hash_password, verify_password
from domain.auth.principal import Principal, new_user_id
from domain.auth.sessions import (
    generate_session_id,
    hash_session_id,
)
from infrastructure.auth.errors import (
    AuthStoreError,
    DuplicateUsernameError,
    MembershipRequiredError,
    UserNotFoundError,
)
from infrastructure.catalog import _connection
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_schema import apply_migrations
from infrastructure.catalog.workspace import require_workspace_id

_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_USERNAME_MAX_LEN = 64
_PASSWORD_MAX_LEN = 1024
_ATTEMPT_RETENTION = timedelta(days=7)

# Fixed dummy hash so missing-user auth takes the same scrypt path as a hit.
_DUMMY_PASSWORD_HASH = hash_password("kernector-timing-dummy")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_instant(value: str) -> datetime:
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        return instant.replace(tzinfo=UTC)
    return instant


class SqlAuthStore:
    """Persist local auth users, sessions, preferences, and login attempts."""

    def __init__(self, path: Path) -> None:
        self._path = path
        try:
            apply_migrations(path, migrations_dir=_MIGRATIONS)
        except CatalogError as error:
            raise AuthStoreError(
                f"could not apply auth migrations at {path}"
            ) from error

    def create_user(self, username: str, password: str) -> StoredUser:
        """Insert a new user with a hashed password."""
        username = username.strip()
        if not username:
            raise AuthStoreError("username is required")
        if len(username) > _USERNAME_MAX_LEN:
            raise AuthStoreError(
                f"username must be at most {_USERNAME_MAX_LEN} characters"
            )
        if not password:
            raise AuthStoreError("password is required")
        if len(password) > _PASSWORD_MAX_LEN:
            raise AuthStoreError(
                f"password must be at most {_PASSWORD_MAX_LEN} characters"
            )
        user_id = new_user_id()
        now = _now()
        password_hash = hash_password(password)
        with self._connect(write=True) as connection:
            try:
                connection.execute(
                    "INSERT INTO auth_users ("
                    "user_id, username, password_hash, created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?)",
                    (user_id, username, password_hash, now, now),
                )
            except sqlite3.IntegrityError as error:
                raise DuplicateUsernameError(
                    f"username {username!r} already exists"
                ) from error
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not create user at {self._path}"
                ) from error
        return StoredUser(
            user_id=user_id,
            username=username,
            password_hash=password_hash,
            created_at=now,
            updated_at=now,
        )

    def get_user_by_username(self, username: str) -> StoredUser | None:
        """Return the user row for *username*, or ``None``."""
        with self._connect() as connection:
            try:
                row = connection.execute(
                    "SELECT user_id, username, password_hash, created_at, updated_at "
                    "FROM auth_users WHERE username = ?",
                    (username.strip(),),
                ).fetchone()
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not read user at {self._path}"
                ) from error
        if row is None:
            return None
        return _user_from_row(row)

    def get_user(self, user_id: str) -> StoredUser | None:
        """Return the user row for *user_id*, or ``None``."""
        with self._connect() as connection:
            try:
                row = connection.execute(
                    "SELECT user_id, username, password_hash, created_at, updated_at "
                    "FROM auth_users WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not read user at {self._path}"
                ) from error
        if row is None:
            return None
        return _user_from_row(row)

    def authenticate(self, username: str, password: str) -> Principal | None:
        """Return a principal when credentials match, else ``None``."""
        user = self.get_user_by_username(username)
        if user is None:
            verify_password(password, _DUMMY_PASSWORD_HASH)
            return None
        if not verify_password(password, user.password_hash):
            return None
        return Principal(user_id=user.user_id, username=user.username)

    def create_session(
        self,
        user_id: str,
        *,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> tuple[str, StoredSession]:
        """Issue a fresh session for *user_id*; return plaintext id and row."""
        if self.get_user(user_id) is None:
            raise UserNotFoundError(f"user_id {user_id!r} not found")
        clock = now or datetime.now(UTC)
        session_id = generate_session_id()
        session_hash = hash_session_id(session_id)
        created_at = clock.isoformat()
        expires_at = datetime.fromtimestamp(
            clock.timestamp() + ttl_seconds, tz=UTC
        ).isoformat()
        with self._connect(write=True) as connection:
            try:
                connection.execute(
                    "INSERT INTO auth_sessions ("
                    "session_id_hash, user_id, expires_at, revoked_at, created_at"
                    ") VALUES (?, ?, ?, NULL, ?)",
                    (session_hash, user_id, expires_at, created_at),
                )
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not create session at {self._path}"
                ) from error
        return session_id, StoredSession(
            session_id_hash=session_hash,
            user_id=user_id,
            expires_at=expires_at,
            created_at=created_at,
            revoked_at=None,
        )

    def get_session(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
    ) -> StoredSession | None:
        """Return an active (non-revoked, non-expired) session, or ``None``."""
        digest = hash_session_id(session_id)
        with self._connect() as connection:
            try:
                row = connection.execute(
                    "SELECT session_id_hash, user_id, expires_at, revoked_at, created_at "
                    "FROM auth_sessions WHERE session_id_hash = ?",
                    (digest,),
                ).fetchone()
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not read session at {self._path}"
                ) from error
        if row is None:
            return None
        session = _session_from_row(row)
        if session.revoked_at is not None:
            return None
        clock = now or datetime.now(UTC)
        if clock >= _parse_instant(session.expires_at):
            return None
        return session

    def revoke_session(self, session_id: str, *, now: datetime | None = None) -> bool:
        """Mark a session revoked. Return whether a row was updated."""
        digest = hash_session_id(session_id)
        revoked_at = (now or datetime.now(UTC)).isoformat()
        with self._connect(write=True) as connection:
            try:
                cursor = connection.execute(
                    "UPDATE auth_sessions SET revoked_at = ? "
                    "WHERE session_id_hash = ? AND revoked_at IS NULL",
                    (revoked_at, digest),
                )
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not revoke session at {self._path}"
                ) from error
        return cursor.rowcount > 0

    def get_preferences(self, user_id: str) -> StoredPreferences | None:
        """Return stored preferences for *user_id*, or ``None`` if missing."""
        with self._connect() as connection:
            try:
                row = connection.execute(
                    "SELECT user_id, provider, model, updated_at "
                    "FROM auth_user_preferences WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not read preferences at {self._path}"
                ) from error
        if row is None:
            return None
        return StoredPreferences(
            user_id=row["user_id"],
            provider=row["provider"],
            model=row["model"],
            updated_at=row["updated_at"],
        )

    def put_preferences(
        self,
        user_id: str,
        *,
        provider: str | None,
        model: str | None,
    ) -> StoredPreferences:
        """Upsert preferred provider/model for *user_id*."""
        if self.get_user(user_id) is None:
            raise UserNotFoundError(f"user_id {user_id!r} not found")
        updated_at = _now()
        with self._connect(write=True) as connection:
            try:
                connection.execute(
                    "INSERT INTO auth_user_preferences ("
                    "user_id, provider, model, updated_at"
                    ") VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "provider = excluded.provider, "
                    "model = excluded.model, "
                    "updated_at = excluded.updated_at",
                    (user_id, provider, model, updated_at),
                )
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not write preferences at {self._path}"
                ) from error
        return StoredPreferences(
            user_id=user_id,
            provider=provider,
            model=model,
            updated_at=updated_at,
        )

    def get_login_attempts(self, username: str) -> LoginAttemptState | None:
        """Return login-attempt state for *username*, or ``None``."""
        with self._connect() as connection:
            try:
                row = connection.execute(
                    "SELECT username, failure_count, locked_until, updated_at "
                    "FROM auth_login_attempts WHERE username = ?",
                    (username.strip(),),
                ).fetchone()
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not read login attempts at {self._path}"
                ) from error
        if row is None:
            return None
        return LoginAttemptState(
            username=row["username"],
            failure_count=int(row["failure_count"]),
            locked_until=row["locked_until"],
            updated_at=row["updated_at"],
        )

    def claim_login_attempt(
        self,
        username: str,
        *,
        max_failures: int,
        lockout_seconds: int,
        now: datetime | None = None,
    ) -> LoginAttemptState | Literal["locked"]:
        """Atomically check lockout and increment failure_count before verify."""
        username = username.strip()
        if not username or len(username) > _USERNAME_MAX_LEN:
            # Reject oversized names without writing unbounded rows.
            return "locked"
        clock = now or datetime.now(UTC)
        updated_at = clock.isoformat()
        retention_cutoff = (clock - _ATTEMPT_RETENTION).isoformat()
        with self._connect(write=True) as connection:
            try:
                # Only prune rows that are not still locked (lockout may exceed 7d).
                connection.execute(
                    "DELETE FROM auth_login_attempts "
                    "WHERE updated_at < ? "
                    "AND (locked_until IS NULL OR locked_until < ?)",
                    (retention_cutoff, updated_at),
                )
                row = connection.execute(
                    "SELECT username, failure_count, locked_until, updated_at "
                    "FROM auth_login_attempts WHERE username = ?",
                    (username,),
                ).fetchone()
                failure_count = 1
                if row is not None:
                    locked_until_raw = row["locked_until"]
                    if locked_until_raw is not None:
                        locked_until_dt = _parse_instant(locked_until_raw)
                        if clock < locked_until_dt:
                            return "locked"
                        # Lockout expired — start a fresh window.
                        failure_count = 1
                    else:
                        failure_count = int(row["failure_count"]) + 1
                locked_until: str | None = None
                if failure_count >= max_failures:
                    locked_until = datetime.fromtimestamp(
                        clock.timestamp() + lockout_seconds, tz=UTC
                    ).isoformat()
                connection.execute(
                    "INSERT INTO auth_login_attempts ("
                    "username, failure_count, locked_until, updated_at"
                    ") VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (username) DO UPDATE SET "
                    "failure_count = excluded.failure_count, "
                    "locked_until = excluded.locked_until, "
                    "updated_at = excluded.updated_at",
                    (username, failure_count, locked_until, updated_at),
                )
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not write login attempts at {self._path}"
                ) from error
        return LoginAttemptState(
            username=username,
            failure_count=failure_count,
            locked_until=locked_until,
            updated_at=updated_at,
        )

    def record_login_failure(
        self,
        username: str,
        *,
        max_failures: int,
        lockout_seconds: int,
        now: datetime | None = None,
    ) -> LoginAttemptState:
        """Increment failure count (compat wrapper around claim_login_attempt)."""
        result = self.claim_login_attempt(
            username,
            max_failures=max_failures,
            lockout_seconds=lockout_seconds,
            now=now,
        )
        if result == "locked":
            state = self.get_login_attempts(username)
            if state is not None:
                return state
            clock = now or datetime.now(UTC)
            return LoginAttemptState(
                username=username.strip(),
                failure_count=max_failures,
                locked_until=datetime.fromtimestamp(
                    clock.timestamp() + lockout_seconds, tz=UTC
                ).isoformat(),
                updated_at=clock.isoformat(),
            )
        return result

    def clear_login_attempts(self, username: str) -> None:
        """Clear failure/lockout state after a successful login."""
        with self._connect(write=True) as connection:
            try:
                connection.execute(
                    "DELETE FROM auth_login_attempts WHERE username = ?",
                    (username.strip(),),
                )
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not clear login attempts at {self._path}"
                ) from error

    def is_locked(
        self, username: str, *, now: datetime | None = None
    ) -> bool:
        """Return whether *username* is currently locked out."""
        state = self.get_login_attempts(username)
        if state is None or state.locked_until is None:
            return False
        clock = now or datetime.now(UTC)
        return clock < _parse_instant(state.locked_until)

    def grant_membership(
        self, principal_id: str, workspace_id: str
    ) -> WorkspaceMembership:
        """Ensure an active membership with opaque ``role="member"``."""
        workspace_id = require_workspace_id(workspace_id)
        if self.get_user(principal_id) is None:
            raise UserNotFoundError("user not found")
        now = _now()
        with self._connect(write=True) as connection:
            try:
                connection.execute(
                    "INSERT INTO auth_workspace_memberships ("
                    "principal_id, workspace_id, role, status, created_at, updated_at"
                    ") VALUES (?, ?, ?, 'active', ?, ?) "
                    "ON CONFLICT(principal_id, workspace_id) DO UPDATE SET "
                    "role = excluded.role, status = 'active', "
                    "updated_at = excluded.updated_at",
                    (principal_id, workspace_id, MEMBER_ROLE, now, now),
                )
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not grant membership at {self._path}"
                ) from error
        membership = self.get_membership(principal_id, workspace_id)
        if membership is None:
            raise AuthStoreError(
                f"could not read membership after grant at {self._path}"
            )
        return membership

    def get_membership(
        self, principal_id: str, workspace_id: str
    ) -> WorkspaceMembership | None:
        """Return the membership row, or ``None`` when absent."""
        workspace_id = require_workspace_id(workspace_id)
        with self._connect() as connection:
            try:
                row = connection.execute(
                    "SELECT principal_id, workspace_id, role, status "
                    "FROM auth_workspace_memberships "
                    "WHERE principal_id = ? AND workspace_id = ?",
                    (principal_id, workspace_id),
                ).fetchone()
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not read membership at {self._path}"
                ) from error
        if row is None:
            return None
        return _membership_from_row(row)

    def list_memberships(self, principal_id: str) -> tuple[WorkspaceMembership, ...]:
        """Return every membership for *principal_id*."""
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    "SELECT principal_id, workspace_id, role, status "
                    "FROM auth_workspace_memberships "
                    "WHERE principal_id = ? "
                    "ORDER BY workspace_id COLLATE BINARY",
                    (principal_id,),
                ).fetchall()
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not list memberships at {self._path}"
                ) from error
        return tuple(_membership_from_row(row) for row in rows)

    def disable_membership(self, principal_id: str, workspace_id: str) -> bool:
        """Mark membership disabled. Return whether a row was updated."""
        return self._set_membership_status(principal_id, workspace_id, "disabled")

    def revoke_membership(self, principal_id: str, workspace_id: str) -> bool:
        """Mark membership revoked. Return whether a row was updated."""
        return self._set_membership_status(principal_id, workspace_id, "revoked")

    def grant_membership_with_projects(
        self,
        principal_id: str,
        workspace_id: str,
        project_ids: tuple[str, ...],
    ) -> tuple[WorkspaceMembership, tuple[ProjectGrant, ...]]:
        """Atomically ensure active membership and active grants for *project_ids*.

        Callers must validate that every project exists in the bound workspace
        before invoking this method. Raises ``UserNotFoundError`` when the
        principal is missing.
        """
        workspace_id = require_workspace_id(workspace_id)
        if self.get_user(principal_id) is None:
            raise UserNotFoundError("user not found")
        cleaned: list[str] = []
        for project_id in project_ids:
            value = project_id.strip()
            if not value:
                raise AuthStoreError("project_id is required")
            cleaned.append(value)
        if not cleaned:
            raise AuthStoreError("project_id is required")
        now = _now()
        with self._connect(write=True) as connection:
            try:
                connection.execute(
                    "INSERT INTO auth_workspace_memberships ("
                    "principal_id, workspace_id, role, status, created_at, updated_at"
                    ") VALUES (?, ?, ?, 'active', ?, ?) "
                    "ON CONFLICT(principal_id, workspace_id) DO UPDATE SET "
                    "role = excluded.role, status = 'active', "
                    "updated_at = excluded.updated_at",
                    (principal_id, workspace_id, MEMBER_ROLE, now, now),
                )
                for project_id in cleaned:
                    connection.execute(
                        "INSERT INTO auth_project_grants ("
                        "principal_id, workspace_id, project_id, status, "
                        "created_at, updated_at"
                        ") VALUES (?, ?, ?, 'active', ?, ?) "
                        "ON CONFLICT(principal_id, workspace_id, project_id) "
                        "DO UPDATE SET status = 'active', "
                        "updated_at = excluded.updated_at",
                        (principal_id, workspace_id, project_id, now, now),
                    )
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not grant workspace access at {self._path}"
                ) from error
        membership = self.get_membership(principal_id, workspace_id)
        if membership is None:
            raise AuthStoreError(
                f"could not read membership after grant at {self._path}"
            )
        grants = tuple(
            grant
            for grant in self.list_project_grants(principal_id, workspace_id)
            if grant.project_id in cleaned and grant.status == "active"
        )
        return membership, grants

    def grant_project(
        self, principal_id: str, workspace_id: str, project_id: str
    ) -> ProjectGrant:
        """Ensure an active project grant under an active membership."""
        workspace_id = require_workspace_id(workspace_id)
        project_id = project_id.strip()
        if not project_id:
            raise AuthStoreError("project_id is required")
        membership = self.get_membership(principal_id, workspace_id)
        if membership is None or membership.status != "active":
            raise MembershipRequiredError("active membership required")
        now = _now()
        with self._connect(write=True) as connection:
            try:
                connection.execute(
                    "INSERT INTO auth_project_grants ("
                    "principal_id, workspace_id, project_id, status, "
                    "created_at, updated_at"
                    ") VALUES (?, ?, ?, 'active', ?, ?) "
                    "ON CONFLICT(principal_id, workspace_id, project_id) DO UPDATE SET "
                    "status = 'active', updated_at = excluded.updated_at",
                    (principal_id, workspace_id, project_id, now, now),
                )
            except sqlite3.IntegrityError as error:
                raise MembershipRequiredError(
                    "active membership required"
                ) from error
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not grant project at {self._path}"
                ) from error
        grants = self.list_project_grants(principal_id, workspace_id)
        for grant in grants:
            if grant.project_id == project_id:
                return grant
        raise AuthStoreError(
            f"could not read project grant after write at {self._path}"
        )

    def list_project_grants(
        self, principal_id: str, workspace_id: str
    ) -> tuple[ProjectGrant, ...]:
        """Return project grants for one principal in one workspace."""
        workspace_id = require_workspace_id(workspace_id)
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    "SELECT principal_id, workspace_id, project_id, status "
                    "FROM auth_project_grants "
                    "WHERE principal_id = ? AND workspace_id = ? "
                    "ORDER BY project_id COLLATE BINARY",
                    (principal_id, workspace_id),
                ).fetchall()
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not list project grants at {self._path}"
                ) from error
        return tuple(_project_grant_from_row(row) for row in rows)

    def revoke_project_grant(
        self, principal_id: str, workspace_id: str, project_id: str
    ) -> bool:
        """Mark the grant revoked. Return whether a row was updated."""
        workspace_id = require_workspace_id(workspace_id)
        now = _now()
        with self._connect(write=True) as connection:
            try:
                cursor = connection.execute(
                    "UPDATE auth_project_grants "
                    "SET status = 'revoked', updated_at = ? "
                    "WHERE principal_id = ? AND workspace_id = ? AND project_id = ?",
                    (now, principal_id, workspace_id, project_id),
                )
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not revoke project grant at {self._path}"
                ) from error
            return cursor.rowcount > 0

    def _set_membership_status(
        self, principal_id: str, workspace_id: str, status: str
    ) -> bool:
        workspace_id = require_workspace_id(workspace_id)
        now = _now()
        with self._connect(write=True) as connection:
            try:
                cursor = connection.execute(
                    "UPDATE auth_workspace_memberships "
                    "SET status = ?, updated_at = ? "
                    "WHERE principal_id = ? AND workspace_id = ?",
                    (status, now, principal_id, workspace_id),
                )
            except sqlite3.Error as error:
                raise AuthStoreError(
                    f"could not update membership at {self._path}"
                ) from error
            return cursor.rowcount > 0

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        try:
            connection = _connection.connect(self._path)
            connection.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as error:
            raise AuthStoreError(
                f"could not open auth store at {self._path}"
            ) from error
        try:
            if write:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                except sqlite3.Error as error:
                    raise AuthStoreError(
                        f"could not begin auth transaction at {self._path}"
                    ) from error
            yield connection
            if write:
                try:
                    connection.commit()
                except sqlite3.Error as error:
                    raise AuthStoreError(
                        f"could not commit auth transaction at {self._path}"
                    ) from error
        except AuthStoreError:
            if write:
                connection.rollback()
            raise
        except Exception:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()


def _user_from_row(row: sqlite3.Row) -> StoredUser:
    return StoredUser(
        user_id=row["user_id"],
        username=row["username"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _session_from_row(row: sqlite3.Row) -> StoredSession:
    return StoredSession(
        session_id_hash=row["session_id_hash"],
        user_id=row["user_id"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        revoked_at=row["revoked_at"],
    )


def _membership_from_row(row: sqlite3.Row) -> WorkspaceMembership:
    return WorkspaceMembership(
        principal_id=row["principal_id"],
        workspace_id=row["workspace_id"],
        role=row["role"],
        status=row["status"],
    )


def _project_grant_from_row(row: sqlite3.Row) -> ProjectGrant:
    return ProjectGrant(
        principal_id=row["principal_id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        status=row["status"],
    )
