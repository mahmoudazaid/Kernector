"""Build MCP access-profile use cases from settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from application.errors import ConfigurationError
from application.mcp_access.profiles import (
    CreateAccessProfile,
    DisableAccessProfile,
    GetAccessProfile,
    ListAccessProfiles,
    RevokeAccessProfile,
    RotateAccessProfileToken,
    SetAccessProfileExpiration,
    UpdateAccessProfileAllowlist,
)
from domain.mcp_access.errors import ProjectNotInWorkspaceError
from domain.mcp_access.models import McpAccessProfile
from infrastructure.config import Settings
from infrastructure.mcp_access.sql_store import (
    SqlMcpAccessProfileStore,
    authenticate_access_token,
)


@dataclass(frozen=True, slots=True)
class McpAccessUseCases:
    create: CreateAccessProfile
    list: ListAccessProfiles
    get: GetAccessProfile
    rotate: RotateAccessProfileToken
    disable: DisableAccessProfile
    revoke: RevokeAccessProfile
    set_expiration: SetAccessProfileExpiration
    update_allowlist: UpdateAccessProfileAllowlist
    store: SqlMcpAccessProfileStore


def build_mcp_access_store(settings: Settings) -> SqlMcpAccessProfileStore:
    from composition.container import _require_workspace_id

    path = settings.document_catalog.sql_path
    if path is None:
        raise ConfigurationError(
            "DOCUMENT_CATALOG_SQL_PATH is blank; unset it to use the "
            "data/catalog/catalog.sqlite default"
        )
    return SqlMcpAccessProfileStore(path, _require_workspace_id(settings))


def _mcp_profile_create_gate(
    user_id: str, workspace_id: str, project_id: str
) -> None:
    """Require user existence, active membership, and project can_read (#447)."""
    from composition.auth import (
        build_auth_store,
        build_project_access_policy,
        resolve_trusted_project_access_caller,
    )
    from domain.auth.principal import Principal

    auth = build_auth_store()
    user = auth.get_user(user_id)
    if user is None:
        raise ValueError(f"unknown user_id {user_id!r}")
    principal = Principal(user_id=user.user_id, username=user.username)
    try:
        caller = resolve_trusted_project_access_caller(
            principal, workspace_id, auth
        )
    except Exception as error:
        raise ValueError(
            "active workspace membership is required for MCP profile principal"
        ) from error
    policy = build_project_access_policy()
    if not policy.can_read(caller, project_id):
        raise ProjectNotInWorkspaceError(project_id)


def build_mcp_access_use_cases(settings: Settings) -> McpAccessUseCases:
    store = build_mcp_access_store(settings)
    return McpAccessUseCases(
        create=CreateAccessProfile(store=store, create_gate=_mcp_profile_create_gate),
        list=ListAccessProfiles(store=store),
        get=GetAccessProfile(store=store),
        rotate=RotateAccessProfileToken(store=store),
        disable=DisableAccessProfile(store=store),
        revoke=RevokeAccessProfile(store=store),
        set_expiration=SetAccessProfileExpiration(store=store),
        update_allowlist=UpdateAccessProfileAllowlist(store=store),
        store=store,
    )


def authenticate_mcp_profile_token(
    path: Path, plaintext_token: str
) -> McpAccessProfile | None:
    """Resolve a profile bearer for the MCP presentation adapter."""
    return authenticate_access_token(path, plaintext_token)
