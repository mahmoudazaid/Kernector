"""SQLite store for local users, sessions, and preferences (#182)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from domain.auth.passwords import hash_password, verify_password
from domain.auth.principal import Principal, new_user_id
from domain.auth.sessions import (
    generate_session_id,
    hash_session_id,
)
from infrastructure.auth.errors import (
    AuthStoreError,
    DuplicateUsernameError,
    UserNotFoundError,
)
from infrastructure.auth.models import (
    LoginAttemptState,
    StoredPreferences,
    StoredSession,
    StoredUser,
)
from infrastructure.catalog import _connection
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_schema import apply_migrations

_MIGRATIONS = Path(__file__).resolve().parent / "migrations"


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
        if not password:
            raise AuthStoreError("password is required")
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

    def record_login_failure(
        self,
        username: str,
        *,
        max_failures: int,
        lockout_seconds: int,
        now: datetime | None = None,
    ) -> LoginAttemptState:
        """Increment failure count and set lockout when threshold is reached."""
        username = username.strip()
        clock = now or datetime.now(UTC)
        updated_at = clock.isoformat()
        existing = self.get_login_attempts(username)
        failure_count = 1 if existing is None else existing.failure_count + 1
        locked_until: str | None = None
        if failure_count >= max_failures:
            locked_until = datetime.fromtimestamp(
                clock.timestamp() + lockout_seconds, tz=UTC
            ).isoformat()
        with self._connect(write=True) as connection:
            try:
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

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = _connection.connect(self._path)
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
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
