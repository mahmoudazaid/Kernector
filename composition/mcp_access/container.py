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


def build_mcp_access_use_cases(settings: Settings) -> McpAccessUseCases:
    store = build_mcp_access_store(settings)
    return McpAccessUseCases(
        create=CreateAccessProfile(store=store),
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
