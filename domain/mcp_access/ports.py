"""Ports for MCP access-profile persistence (#324)."""

from __future__ import annotations

from typing import Protocol

from domain.mcp_access.models import McpAccessProfile


class McpAccessProfileStore(Protocol):
    """Workspace-bound store for MCP access profiles."""

    def add(self, profile: McpAccessProfile) -> None:
        """Insert a profile that already has ``token_hash`` set."""
        ...

    def get(self, profile_id: str) -> McpAccessProfile | None: ...

    def list(self) -> tuple[McpAccessProfile, ...]: ...

    def update(self, profile: McpAccessProfile) -> None: ...

    def authenticate(self, plaintext_token: str) -> McpAccessProfile | None:
        """Return the active, non-expired profile for *plaintext_token*, or None."""
        ...

    def project_exists(self, project_id: str) -> bool:
        """True when *project_id* exists in this workspace."""
        ...
