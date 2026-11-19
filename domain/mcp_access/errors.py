"""Errors for MCP access-profile operations."""

from __future__ import annotations


class McpAccessProfileError(Exception):
    """Base for access-profile failures."""


class ProjectNotInWorkspaceError(McpAccessProfileError):
    """The bound ``project_id`` is not in the profile's workspace."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__(f"project not in workspace: {project_id}")


class AccessProfileNotFoundError(McpAccessProfileError):
    """No access profile for the given id in this workspace."""

    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id
        super().__init__(f"access profile not found: {profile_id}")


class IsolationUnsafeToolError(McpAccessProfileError):
    """Allowlist update requested a tool that cannot guarantee isolation."""

    def __init__(self, tool_ids: tuple[str, ...]) -> None:
        self.tool_ids = tool_ids
        super().__init__(
            "one or more tools cannot guarantee project isolation"
        )


class InvalidAccessProfileExpirationError(McpAccessProfileError):
    """``expires_at`` is not a parseable future ISO-8601 timestamp."""

    def __init__(self, expires_at: str) -> None:
        self.expires_at = expires_at
        super().__init__(
            "expires_at must be a future ISO-8601 timestamp"
        )
