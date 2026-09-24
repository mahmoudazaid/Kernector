"""MCP caller identity and access-policy seams (composition-owned)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


class MissingCallerContextError(Exception):
    """No authenticated MCP caller context is available (fail closed)."""


@dataclass(frozen=True, slots=True)
class McpCallerContext:
    """Authenticated caller for one MCP request.

    Attributes:
        workspace_id: Server-bound workspace (never from client args).
        profile_id: Access-profile id (single-profile MVP).
        allowlist: Tool ids the profile may use.
    """

    workspace_id: str
    profile_id: str
    allowlist: frozenset[str]


class CallerContextResolver(Protocol):
    """Resolve the authenticated caller for an MCP handler invocation."""

    def resolve(self, request: object | None) -> McpCallerContext:
        """Return the caller for this invocation.

        Args:
            request: Transport request when present (ASGI); ``None`` for
                in-memory protocol clients that bypass HTTP middleware.

        Raises:
            MissingCallerContextError: No authenticated context (fail closed).
        """
        ...


@dataclass(frozen=True, slots=True)
class FixedCallerContextResolver:
    """Test/protocol resolver that always returns one fixed context."""

    context: McpCallerContext

    def resolve(self, request: object | None) -> McpCallerContext:
        _ = request
        return self.context


class RequestScopedCallerContextResolver:
    """Production resolver: read ``request.state.mcp_caller`` set by ASGI auth."""

    STATE_ATTR = "mcp_caller"

    def resolve(self, request: object | None) -> McpCallerContext:
        if request is None:
            raise MissingCallerContextError("missing authenticated caller context")
        state = getattr(request, "state", None)
        if state is None:
            raise MissingCallerContextError("missing authenticated caller context")
        caller = getattr(state, self.STATE_ATTR, None)
        if not isinstance(caller, McpCallerContext):
            raise MissingCallerContextError("missing authenticated caller context")
        return caller


@dataclass(frozen=True, slots=True)
class McpAccessPolicy:
    """Effective-tool policy for the single-profile MVP.

    Effective tools = contributed tool ids ∩ enabled packs ∩ profile allowlist.
    Core tools use pack_id ``None`` and require allowlist membership.
    """

    enabled_packs: frozenset[str]
    # tool_id -> pack_id; core tools map to None
    tool_pack: Mapping[str, str | None]

    def is_effective(self, caller: McpCallerContext, tool_id: str) -> bool:
        """Return True when *tool_id* is contributed, pack-enabled, and allowlisted."""
        if tool_id not in self.tool_pack:
            return False
        if tool_id not in caller.allowlist:
            return False
        pack_id = self.tool_pack[tool_id]
        if pack_id is None:
            return True
        return pack_id in self.enabled_packs

    def effective_ids(self, caller: McpCallerContext) -> tuple[str, ...]:
        """Return sorted effective tool ids for *caller*."""
        return tuple(
            sorted(
                tool_id
                for tool_id in self.tool_pack
                if self.is_effective(caller, tool_id)
            )
        )


def build_access_policy(
    *,
    enabled_packs: Sequence[str],
    tool_pack: Mapping[str, str | None],
) -> McpAccessPolicy:
    """Construct an access policy from deployment pack enablement."""
    return McpAccessPolicy(
        enabled_packs=frozenset(enabled_packs),
        tool_pack=dict(tool_pack),
    )
