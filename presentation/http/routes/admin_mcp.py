"""Admin MCP access-profile management routes (#324)."""

from __future__ import annotations

from fastapi import APIRouter

from application.mcp_access.profiles import CreateAccessProfileRequest
from composition.mcp.isolation import ISOLATION_BLOCKED_REASON, is_isolation_safe
from composition.mcp.settings import build_mcp_registry_for_runtime
from composition.mcp.tool_registry import mcp_tool_name
from domain.mcp_access.models import McpAccessProfile
from domain.tool_approval import ToolApprovalPolicy
from presentation.http.admin_auth import AdminAuthDep
from presentation.http.deps import McpAccessUseCasesDep, SettingsDep
from presentation.http.errors import problem_responses
from presentation.http.schemas import (
    CreateMcpAccessProfileBody,
    McpAccessProfileCreatedResponse,
    McpAccessProfileResponse,
    McpServerInfoResponse,
    McpToolCatalogItemResponse,
    McpToolCatalogResponse,
    UpdateMcpAllowlistBody,
)

router = APIRouter(prefix="/api/v1/admin/mcp", tags=["admin-mcp"])


def _profile_response(profile: McpAccessProfile) -> McpAccessProfileResponse:
    return McpAccessProfileResponse(
        profile_id=profile.profile_id,
        project_id=profile.project_id,
        name=profile.name,
        allowlist=sorted(profile.allowlist),
        status=profile.status.value,
        expires_at=profile.expires_at,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        description=profile.description,
        disabled_at=profile.disabled_at,
        revoked_at=profile.revoked_at,
        user_id=profile.user_id,
    )


@router.get(
    "/server",
    responses=problem_responses(401, 500),
)
def mcp_server_info(_admin: AdminAuthDep) -> McpServerInfoResponse:
    """Return hosted MCP endpoint metadata (not remote MCP consume)."""
    return McpServerInfoResponse(
        endpoint="/mcp",
        transport="streamable-http",
        auth_mode="profile-bearer",
        status="configured",
    )


@router.get(
    "/tools",
    responses=problem_responses(401, 500),
)
def list_mcp_tools(
    _admin: AdminAuthDep, settings: SettingsDep
) -> McpToolCatalogResponse:
    """List discoverable MCP tools with enablement and isolation state."""
    registry = build_mcp_registry_for_runtime(settings)
    approval = ToolApprovalPolicy()
    items: list[McpToolCatalogItemResponse] = []
    for tool_id, pack_id in sorted(
        registry.contributed_tool_pack.items(), key=lambda pair: pair[0]
    ):
        allowlistable = is_isolation_safe(tool_id)
        items.append(
            McpToolCatalogItemResponse(
                tool_id=tool_id,
                name=mcp_tool_name(tool_id),
                kind="core" if pack_id is None else "pack",
                pack_id=pack_id,
                allowlistable=allowlistable,
                side_effecting=approval.requires_approval(tool_id),
                unavailable_reason=None if allowlistable else ISOLATION_BLOCKED_REASON,
            )
        )
    return McpToolCatalogResponse(tools=items)


@router.get(
    "/profiles",
    responses=problem_responses(401, 500),
)
def list_profiles(
    _admin: AdminAuthDep, use_cases: McpAccessUseCasesDep
) -> list[McpAccessProfileResponse]:
    return [_profile_response(item) for item in use_cases.list.execute()]


@router.post(
    "/profiles",
    status_code=201,
    responses=problem_responses(401, 404, 422, 500),
)
def create_profile(
    body: CreateMcpAccessProfileBody,
    _admin: AdminAuthDep,
    use_cases: McpAccessUseCasesDep,
) -> McpAccessProfileCreatedResponse:
    created = use_cases.create.execute(
        CreateAccessProfileRequest(
            project_id=body.project_id,
            name=body.name,
            user_id=body.user_id,
            expires_at=body.expires_at,
            description=body.description,
        )
    )
    return McpAccessProfileCreatedResponse(
        profile=_profile_response(created.profile),
        plaintext_token=created.plaintext_token,
    )


@router.get(
    "/profiles/{profile_id}",
    responses=problem_responses(401, 404, 500),
)
def get_profile(
    profile_id: str, _admin: AdminAuthDep, use_cases: McpAccessUseCasesDep
) -> McpAccessProfileResponse:
    return _profile_response(use_cases.get.execute(profile_id))


@router.put(
    "/profiles/{profile_id}/allowlist",
    responses=problem_responses(401, 404, 422, 500),
)
def update_allowlist(
    profile_id: str,
    body: UpdateMcpAllowlistBody,
    _admin: AdminAuthDep,
    use_cases: McpAccessUseCasesDep,
) -> McpAccessProfileResponse:
    profile = use_cases.update_allowlist.execute(
        profile_id, allowlist=frozenset(body.allowlist)
    )
    return _profile_response(profile)


@router.post(
    "/profiles/{profile_id}/rotate",
    responses=problem_responses(401, 404, 500),
)
def rotate_profile(
    profile_id: str, _admin: AdminAuthDep, use_cases: McpAccessUseCasesDep
) -> McpAccessProfileCreatedResponse:
    created = use_cases.rotate.execute(profile_id)
    return McpAccessProfileCreatedResponse(
        profile=_profile_response(created.profile),
        plaintext_token=created.plaintext_token,
    )


@router.post(
    "/profiles/{profile_id}/disable",
    responses=problem_responses(401, 404, 500),
)
def disable_profile(
    profile_id: str, _admin: AdminAuthDep, use_cases: McpAccessUseCasesDep
) -> McpAccessProfileResponse:
    return _profile_response(use_cases.disable.execute(profile_id))


@router.post(
    "/profiles/{profile_id}/revoke",
    responses=problem_responses(401, 404, 500),
)
def revoke_profile(
    profile_id: str, _admin: AdminAuthDep, use_cases: McpAccessUseCasesDep
) -> McpAccessProfileResponse:
    return _profile_response(use_cases.revoke.execute(profile_id))
