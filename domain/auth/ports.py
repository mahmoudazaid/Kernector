"""Ports for local auth persistence (#182, #446)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from domain.auth.models import (
    LoginAttemptState,
    ProjectGrant,
    StoredPreferences,
    StoredSession,
    StoredUser,
    WorkspaceMembership,
)
from domain.auth.principal import Principal

ClaimLoginResult = LoginAttemptState | Literal["locked"]


class MembershipStore(Protocol):
    """Persistence for principal-to-workspace membership (#446)."""

    def grant_membership(
        self, principal_id: str, workspace_id: str
    ) -> WorkspaceMembership:
        """Ensure an active membership with opaque ``role="member"``."""
        ...

    def get_membership(
        self, principal_id: str, workspace_id: str
    ) -> WorkspaceMembership | None:
        """Return the membership row, or ``None`` when absent."""
        ...

    def list_memberships(self, principal_id: str) -> tuple[WorkspaceMembership, ...]:
        """Return every membership for *principal_id*."""
        ...

    def disable_membership(self, principal_id: str, workspace_id: str) -> bool:
        """Mark membership disabled. Return whether a row was updated."""
        ...

    def revoke_membership(self, principal_id: str, workspace_id: str) -> bool:
        """Mark membership revoked. Return whether a row was updated."""
        ...


class ProjectGrantStore(Protocol):
    """Persistence for explicit project grants (#446).

    Grants are keyed by ``(principal_id, workspace_id, project_id)``. An active
    workspace membership is required before a grant may be written.
    """

    def grant_project(
        self, principal_id: str, workspace_id: str, project_id: str
    ) -> ProjectGrant:
        """Ensure an active project grant under an active membership."""
        ...

    def list_project_grants(
        self, principal_id: str, workspace_id: str
    ) -> tuple[ProjectGrant, ...]:
        """Return project grants for one principal in one workspace."""
        ...

    def revoke_project_grant(
        self, principal_id: str, workspace_id: str, project_id: str
    ) -> bool:
        """Mark the grant revoked. Return whether a row was updated."""
        ...


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
