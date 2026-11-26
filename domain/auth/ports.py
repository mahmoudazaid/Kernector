"""Ports for local auth persistence (#182)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from domain.auth.models import (
    LoginAttemptState,
    StoredPreferences,
    StoredSession,
    StoredUser,
)
from domain.auth.principal import Principal

ClaimLoginResult = LoginAttemptState | Literal["locked"]


class AuthStore(Protocol):
    """Persistence for local users, sessions, preferences, and lockouts."""

    def create_user(self, username: str, password: str) -> StoredUser: ...

    def get_user_by_username(self, username: str) -> StoredUser | None: ...

    def get_user(self, user_id: str) -> StoredUser | None: ...

    def authenticate(self, username: str, password: str) -> Principal | None: ...

    def create_session(
        self,
        user_id: str,
        *,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> tuple[str, StoredSession]: ...

    def get_session(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
    ) -> StoredSession | None: ...

    def revoke_session(
        self, session_id: str, *, now: datetime | None = None
    ) -> bool: ...

    def get_preferences(self, user_id: str) -> StoredPreferences | None: ...

    def put_preferences(
        self,
        user_id: str,
        *,
        provider: str | None,
        model: str | None,
    ) -> StoredPreferences: ...

    def claim_login_attempt(
        self,
        username: str,
        *,
        max_failures: int,
        lockout_seconds: int,
        now: datetime | None = None,
    ) -> ClaimLoginResult:
        """Atomically check lockout and reserve a failure slot before verify."""
        ...

    def clear_login_attempts(self, username: str) -> None: ...

    def is_locked(
        self, username: str, *, now: datetime | None = None
    ) -> bool: ...
