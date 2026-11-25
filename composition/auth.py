"""Composition wiring for local user auth (#182)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from application.errors import ConfigurationError
from domain.auth.csrf import csrf_tokens_match, derive_csrf_token
from domain.auth.principal import Principal
from infrastructure.auth.errors import AuthStoreError, DuplicateUsernameError
from infrastructure.auth.models import StoredPreferences, StoredUser
from infrastructure.auth.sql_store import SqlAuthStore
from infrastructure.config import AuthSettings, Settings, load_settings


@lru_cache(maxsize=1)
def _auth_store_for_path(path: str) -> SqlAuthStore:
    return SqlAuthStore(Path(path))


def build_auth_store(settings: Settings | None = None) -> SqlAuthStore:
    """Return the process auth SQLite store."""
    resolved = settings if settings is not None else load_settings()
    return _auth_store_for_path(str(resolved.auth.sql_path))


def clear_auth_store_cache() -> None:
    """Drop the cached auth store (tests)."""
    _auth_store_for_path.cache_clear()


def create_local_user(
    username: str,
    password: str,
    *,
    settings: Settings | None = None,
) -> StoredUser:
    """Provision a local user. Raises ConfigurationError-shaped failures."""
    store = build_auth_store(settings)
    try:
        return store.create_user(username, password)
    except DuplicateUsernameError as error:
        raise ConfigurationError(str(error)) from error
    except AuthStoreError as error:
        raise ConfigurationError(str(error)) from error


def auth_settings(settings: Settings | None = None) -> AuthSettings:
    """Return auth settings from *settings* or the process env."""
    resolved = settings if settings is not None else load_settings()
    return resolved.auth


@dataclass(frozen=True, slots=True)
class ResolvedSession:
    """Active session cookie material plus principal."""

    session_id: str
    principal: Principal
    csrf_token: str


def derive_session_csrf(settings: AuthSettings, session_id: str) -> str:
    return derive_csrf_token(settings.csrf_key, session_id)


def resolve_session(
    store: SqlAuthStore,
    settings: AuthSettings,
    session_id: str | None,
) -> ResolvedSession | None:
    if not session_id:
        return None
    row = store.get_session(session_id)
    if row is None:
        return None
    user = store.get_user(row.user_id)
    if user is None:
        return None
    return ResolvedSession(
        session_id=session_id,
        principal=Principal(user_id=user.user_id, username=user.username),
        csrf_token=derive_session_csrf(settings, session_id),
    )


def require_csrf(presented: str | None, expected: str) -> bool:
    if presented is None:
        return False
    return csrf_tokens_match(presented, expected)


def get_preferences(
    store: SqlAuthStore, user_id: str
) -> StoredPreferences | None:
    return store.get_preferences(user_id)


def put_preferences(
    store: SqlAuthStore,
    user_id: str,
    *,
    provider: str | None,
    model: str | None,
) -> StoredPreferences:
    return store.put_preferences(user_id, provider=provider, model=model)
