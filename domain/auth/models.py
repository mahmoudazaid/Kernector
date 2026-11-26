"""Persisted auth record shapes (#182)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredUser:
    """User row without a plaintext password."""

    user_id: str
    username: str
    password_hash: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class StoredSession:
    """Session row keyed by hashed session id."""

    session_id_hash: str
    user_id: str
    expires_at: str
    created_at: str
    revoked_at: str | None = None


@dataclass(frozen=True, slots=True)
class StoredPreferences:
    """Per-user preferred provider/model."""

    user_id: str
    provider: str | None
    model: str | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class LoginAttemptState:
    """Failed-login counter and optional lockout deadline."""

    username: str
    failure_count: int
    locked_until: str | None
    updated_at: str
