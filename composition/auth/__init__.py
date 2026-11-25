"""Composition wiring for local user auth (#182)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from application.auth.login import Login, LoginFailedError, LoginResult
from application.errors import ConfigurationError
from domain.auth.csrf import csrf_tokens_match, derive_csrf_token
from domain.auth.ports import AuthStore
from domain.auth.principal import Principal
from infrastructure.auth.errors import AuthStoreError, DuplicateUsernameError
from infrastructure.auth.models import StoredPreferences, StoredUser
from infrastructure.auth.sql_store import SqlAuthStore
from infrastructure.config import AuthSettings, Settings
from composition.container import load_runtime_settings


@lru_cache(maxsize=1)
def _auth_store_for_path(path: str) -> SqlAuthStore:
    return SqlAuthStore(Path(path))


def build_auth_store(settings: Settings | None = None) -> AuthStore:
    """Return the process auth SQLite store (as the AuthStore port)."""
    resolved = settings if settings is not None else load_runtime_settings()
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
    try:
        store = build_auth_store(settings)
        return store.create_user(username, password)
    except DuplicateUsernameError as error:
        raise ConfigurationError(str(error)) from error
    except AuthStoreError as error:
        raise ConfigurationError(str(error)) from error
    except OSError as error:
        raise ConfigurationError(str(error)) from error


def auth_settings(settings: Settings | None = None) -> AuthSettings:
    """Return auth settings from *settings* or the process env."""
    resolved = settings if settings is not None else load_runtime_settings()
    return resolved.auth


def build_login(settings: Settings | None = None) -> Login:
    """Return the login use case wired to the process auth store."""
    resolved = settings if settings is not None else load_runtime_settings()
    auth = resolved.auth
    return Login(
        store=build_auth_store(resolved),
        max_failures=auth.login_max_failures,
        lockout_seconds=auth.login_lockout_seconds,
        session_ttl_seconds=auth.session_ttl_seconds,
    )


@dataclass(frozen=True, slots=True)
class ResolvedSession:
    """Active session cookie material plus principal."""

    session_id: str
    principal: Principal
    csrf_token: str


def derive_session_csrf(settings: AuthSettings, session_id: str) -> str:
    return derive_csrf_token(settings.csrf_key, session_id)


def resolve_session(
    store: AuthStore,
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
    store: AuthStore, user_id: str
) -> StoredPreferences | None:
    return store.get_preferences(user_id)


def put_preferences(
    store: AuthStore,
    user_id: str,
    *,
    provider: str | None,
    model: str | None,
) -> StoredPreferences:
    return store.put_preferences(user_id, provider=provider, model=model)


__all__ = [
    "Login",
    "LoginFailedError",
    "LoginResult",
    "ResolvedSession",
    "auth_settings",
    "build_auth_store",
    "build_login",
    "clear_auth_store_cache",
    "create_local_user",
    "derive_session_csrf",
    "get_preferences",
    "put_preferences",
    "require_csrf",
    "resolve_session",
]
