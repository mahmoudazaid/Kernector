"""Create, list, and fetch MCP access profiles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from domain.mcp_access.errors import (
    AccessProfileNotFoundError,
    InvalidAccessProfileExpirationError,
    IsolationUnsafeToolError,
    ProjectNotInWorkspaceError,
)
from domain.mcp_access.models import (
    McpAccessProfile,
    McpAccessProfileStatus,
    new_access_profile_id,
)
from domain.mcp_access.ports import McpAccessProfileStore
from domain.mcp_access.tokens import generate_access_token, hash_access_token


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_clock(value: str) -> datetime:
    clock = datetime.fromisoformat(value)
    if clock.tzinfo is None:
        return clock.replace(tzinfo=UTC)
    return clock


def _normalize_expires_at(expires_at: str | None, *, now: str) -> str | None:
    """Parse and normalize ``expires_at``; reject unparseable or past values."""
    if expires_at is None:
        return None
    if not isinstance(expires_at, str):
        raise InvalidAccessProfileExpirationError(str(expires_at))
    raw = expires_at.strip()
    if not raw:
        return None
    try:
        deadline = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise InvalidAccessProfileExpirationError(raw) from exc
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if deadline <= _parse_clock(now):
        raise InvalidAccessProfileExpirationError(raw)
    return deadline.isoformat()


@dataclass(frozen=True, slots=True)
class CreateAccessProfileRequest:
    project_id: str
    name: str
    expires_at: str | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class CreatedAccessProfile:
    """Create/rotate result: sanitized profile plus one-time plaintext token."""

    profile: McpAccessProfile
    plaintext_token: str


class CreateAccessProfile:
    """Create an independent MCP access profile bound to a project."""

    def __init__(
        self,
        *,
        store: McpAccessProfileStore,
        new_id: Callable[[], str] = new_access_profile_id,
        new_token: Callable[[], str] = generate_access_token,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._store = store
        self._new_id = new_id
        self._new_token = new_token
        self._clock = clock

    def execute(self, request: CreateAccessProfileRequest) -> CreatedAccessProfile:
        name = request.name.strip() if isinstance(request.name, str) else ""
        if not name:
            raise ValueError("name must be non-blank")
        if not self._store.project_exists(request.project_id):
            raise ProjectNotInWorkspaceError(request.project_id)
        plaintext = self._new_token()
        now = self._clock()
        description = (
            request.description.strip()
            if isinstance(request.description, str)
            else ""
        )
        expires_at = _normalize_expires_at(request.expires_at, now=now)
        profile = McpAccessProfile(
            profile_id=self._new_id(),
            workspace_id=_workspace_id(self._store),
            project_id=request.project_id,
            name=name,
            allowlist=frozenset(),
            status=McpAccessProfileStatus.ACTIVE,
            expires_at=expires_at,
            token_hash=hash_access_token(plaintext),
            created_at=now,
            updated_at=now,
            description=description,
        )
        self._store.add(profile)
        return CreatedAccessProfile(profile=profile, plaintext_token=plaintext)


class ListAccessProfiles:
    def __init__(self, *, store: McpAccessProfileStore) -> None:
        self._store = store

    def execute(self) -> tuple[McpAccessProfile, ...]:
        return self._store.list()


class GetAccessProfile:
    def __init__(self, *, store: McpAccessProfileStore) -> None:
        self._store = store

    def execute(self, profile_id: str) -> McpAccessProfile:
        profile = self._store.get(profile_id)
        if profile is None:
            raise AccessProfileNotFoundError(profile_id)
        return profile


class RotateAccessProfileToken:
    """Issue a new token; the previous hash stops authenticating immediately."""

    def __init__(
        self,
        *,
        store: McpAccessProfileStore,
        new_token: Callable[[], str] = generate_access_token,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._store = store
        self._new_token = new_token
        self._clock = clock

    def execute(self, profile_id: str) -> CreatedAccessProfile:
        profile = GetAccessProfile(store=self._store).execute(profile_id)
        plaintext = self._new_token()
        updated = replace(
            profile,
            token_hash=hash_access_token(plaintext),
            updated_at=self._clock(),
        )
        self._store.update(updated)
        return CreatedAccessProfile(profile=updated, plaintext_token=plaintext)


class DisableAccessProfile:
    def __init__(
        self,
        *,
        store: McpAccessProfileStore,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._store = store
        self._clock = clock

    def execute(self, profile_id: str) -> McpAccessProfile:
        profile = GetAccessProfile(store=self._store).execute(profile_id)
        now = self._clock()
        updated = replace(
            profile,
            status=McpAccessProfileStatus.DISABLED,
            disabled_at=now,
            updated_at=now,
        )
        self._store.update(updated)
        return updated


class RevokeAccessProfile:
    def __init__(
        self,
        *,
        store: McpAccessProfileStore,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._store = store
        self._clock = clock

    def execute(self, profile_id: str) -> McpAccessProfile:
        profile = GetAccessProfile(store=self._store).execute(profile_id)
        now = self._clock()
        updated = replace(
            profile,
            status=McpAccessProfileStatus.REVOKED,
            revoked_at=now,
            updated_at=now,
        )
        self._store.update(updated)
        return updated


class SetAccessProfileExpiration:
    def __init__(
        self,
        *,
        store: McpAccessProfileStore,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._store = store
        self._clock = clock

    def execute(self, profile_id: str, *, expires_at: str | None) -> McpAccessProfile:
        profile = GetAccessProfile(store=self._store).execute(profile_id)
        now = self._clock()
        updated = replace(
            profile,
            expires_at=_normalize_expires_at(expires_at, now=now),
            updated_at=now,
        )
        self._store.update(updated)
        return updated


class UpdateAccessProfileAllowlist:
    """Replace a profile allowlist; rejects isolation-unsafe tool ids."""

    def __init__(
        self,
        *,
        store: McpAccessProfileStore,
        clock: Callable[[], str] = _now,
        isolation_safe: Callable[[str], bool] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        if isolation_safe is None:
            from domain.mcp_access.isolation import is_isolation_safe as _safe

            self._isolation_safe = _safe
        else:
            self._isolation_safe = isolation_safe

    def execute(
        self, profile_id: str, *, allowlist: frozenset[str]
    ) -> McpAccessProfile:
        unsafe = tuple(sorted(tool for tool in allowlist if not self._isolation_safe(tool)))
        if unsafe:
            raise IsolationUnsafeToolError(unsafe)
        profile = GetAccessProfile(store=self._store).execute(profile_id)
        updated = replace(
            profile,
            allowlist=frozenset(allowlist),
            updated_at=self._clock(),
        )
        self._store.update(updated)
        return updated


def _workspace_id(store: McpAccessProfileStore) -> str:
    workspace_id = getattr(store, "workspace_id", None)
    if isinstance(workspace_id, str) and workspace_id:
        return workspace_id
    raise TypeError("store must expose workspace_id")
