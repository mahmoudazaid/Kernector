"""MCP access-profile entities (#324)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum


class McpAccessProfileStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    REVOKED = "revoked"


def new_access_profile_id() -> str:
    """Return a fresh opaque access-profile id."""
    return f"mcp_{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class McpAccessProfile:
    """Sanitized access profile — never carries a plaintext token."""

    profile_id: str
    workspace_id: str
    project_id: str
    name: str
    allowlist: frozenset[str]
    status: McpAccessProfileStatus
    expires_at: str | None
    token_hash: str
    created_at: str
    updated_at: str
    description: str = ""
    disabled_at: str | None = None
    revoked_at: str | None = None
