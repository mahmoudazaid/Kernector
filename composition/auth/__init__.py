"""Composition wiring for local user auth (#182, #446)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from application.auth.login import Login, LoginFailedError, LoginResult
from application.errors import ConfigurationError
from composition.auth.project_access import (
    MembershipGrantProjectAccessPolicy,
    _UnitOfWorkProjectLookup,
    build_membership_grant_policy,
)
from composition.auth.trusted_context import (
    NoActiveMembershipError,
    TrustedWorkspaceSelectionRequiredError,
    bootstrap_workspace_id_from_settings,
    process_bound_workspace_id_from_settings,
    resolve_caller_for_principal,
    resolve_trusted_project_access_caller,
    select_trusted_workspace,
)
from composition.container import load_runtime_settings
from domain.auth.csrf import csrf_tokens_match, derive_csrf_token
from domain.auth.ports import AuthStore
from domain.auth.principal import Principal
from domain.project.access import ProjectAccessPolicy
from infrastructure.auth.errors import AuthStoreError, DuplicateUsernameError
from infrastructure.auth.models import StoredPreferences, StoredUser
from infrastructure.auth.sql_store import SqlAuthStore
from infrastructure.config import AuthSettings, Settings


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
    selected_workspace_id: str | None = None


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
        selected_workspace_id=row.selected_workspace_id,
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


def build_project_access_policy(
    settings: Settings | None = None,
) -> ProjectAccessPolicy:
    """Return the membership-and-grant-backed project access policy (#446).

    Does not wire HTTP/MCP callers; #447 owns trusted-context application.
    """
    from composition.container import _require_workspace_id
    from composition.project.container import build_project_store

    resolved = settings if settings is not None else load_runtime_settings()
    store = build_auth_store(resolved)
    project_store = build_project_store(resolved)
    bound_workspace_id = _require_workspace_id(resolved)
    return build_membership_grant_policy(
        memberships=store,
        grants=store,
        projects=_UnitOfWorkProjectLookup(project_store),
        bound_workspace_id=bound_workspace_id,
    )


@dataclass(frozen=True, slots=True)
class WorkspaceAccessGrant:
    """Result of an operator bootstrap grant (#446)."""

    username: str
    user_id: str
    workspace_id: str
    project_ids: tuple[str, ...]


def grant_workspace_access(
    *,
    username: str,
    project_ids: tuple[str, ...] | None = None,
    all_existing_projects: bool = False,
    settings: Settings | None = None,
    auth_store: SqlAuthStore | None = None,
    project_store: object | None = None,
    workspace_id: str | None = None,
) -> WorkspaceAccessGrant:
    """Validate projects, then atomically grant membership and project grants.

    Args:
        username (str): Existing local username.
        project_ids (tuple[str, ...] | None): Explicit project ids to grant.
        all_existing_projects (bool): When True, grant the current workspace
            project snapshot (membership only when empty). Never implied by
            an omitted project list.
        settings (Settings | None): Optional settings override.
        auth_store (SqlAuthStore | None): Test seam for the auth SQLite store.
        project_store (object | None): Test seam for the workspace project store.
        workspace_id (str | None): Test seam for the bound workspace id.

    Returns:
        WorkspaceAccessGrant: Granted principal, workspace, and project ids.

    Raises:
        ConfigurationError: User missing, project selection empty/invalid,
            a requested project does not exist in the bound workspace, or
            auth/project store construction or access fails.
    """
    from composition.container import _require_workspace_id
    from composition.project.container import build_project_store
    from infrastructure.auth.errors import AuthStoreError, UserNotFoundError
    from infrastructure.project.sql_store import ProjectStoreError

    resolved = settings if settings is not None else load_runtime_settings()
    try:
        store = auth_store if auth_store is not None else build_auth_store(resolved)
        projects = (
            project_store
            if project_store is not None
            else build_project_store(resolved)
        )
        bound_workspace = (
            workspace_id
            if workspace_id is not None
            else _require_workspace_id(resolved)
        )

        if all_existing_projects:
            with projects.read() as tx:  # type: ignore[attr-defined]
                selected = tuple(
                    project.project_id for project in tx.projects.list()
                )
        else:
            selected = tuple(project_ids or ())

        if not all_existing_projects and not selected:
            raise ConfigurationError(
                "provide --project-id values or --all-existing-projects"
            )

        if selected:
            with projects.read() as tx:  # type: ignore[attr-defined]
                missing = [
                    project_id
                    for project_id in selected
                    if tx.projects.get(project_id) is None
                ]
            if missing:
                raise ConfigurationError("unknown project")

        user = store.get_user_by_username(username.strip())
        if user is None:
            raise ConfigurationError("user not found")

        if selected:
            store.grant_membership_with_projects(
                user.user_id, bound_workspace, selected
            )
        else:
            # Empty workspace snapshot: membership only so the operator can
            # create the first project via authenticated HTTP (#447).
            store.grant_membership(user.user_id, bound_workspace)
    except ConfigurationError:
        raise
    except UserNotFoundError as error:
        raise ConfigurationError("user not found") from error
    except (AuthStoreError, ProjectStoreError, ValueError, OSError) as error:
        raise ConfigurationError(str(error)) from error

    return WorkspaceAccessGrant(
        username=user.username,
        user_id=user.user_id,
        workspace_id=bound_workspace,
        project_ids=selected,
    )


__all__ = [
    "Login",
    "LoginFailedError",
    "LoginResult",
    "MembershipGrantProjectAccessPolicy",
    "NoActiveMembershipError",
    "ResolvedSession",
    "TrustedWorkspaceSelectionRequiredError",
    "WorkspaceAccessGrant",
    "auth_settings",
    "bootstrap_workspace_id_from_settings",
    "process_bound_workspace_id_from_settings",
    "build_auth_store",
    "build_login",
    "build_project_access_policy",
    "clear_auth_store_cache",
    "create_local_user",
    "derive_session_csrf",
    "get_preferences",
    "grant_workspace_access",
    "put_preferences",
    "require_csrf",
    "resolve_caller_for_principal",
    "resolve_session",
    "resolve_trusted_project_access_caller",
    "select_trusted_workspace",
]
