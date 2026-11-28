"""MCP caller identity and access-policy seams (composition-owned)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from composition.mcp.isolation import is_isolation_safe

if TYPE_CHECKING:
    from domain.project.access import ProjectAccessCaller


class MissingCallerContextError(Exception):
    """No authenticated MCP caller context is available (fail closed)."""


_CURRENT_CALLER: ContextVar[McpCallerContext | None] = ContextVar(
    "mcp_caller_context", default=None
)


def current_caller() -> McpCallerContext | None:
    """Return the caller bound for the in-flight MCP tool invocation, if any."""
    return _CURRENT_CALLER.get()


def bind_caller(caller: McpCallerContext):
    """Bind *caller* for the current tool invocation (context manager)."""
    from contextlib import contextmanager

    @contextmanager
    def _bind():
        token = _CURRENT_CALLER.set(caller)
        try:
            yield
        finally:
            _CURRENT_CALLER.reset(token)

    return _bind()


@dataclass(frozen=True, slots=True)
class McpCallerContext:
    """Authenticated caller for one MCP request.

    Trusted workspace/user identity is taken from ``ProjectAccessCaller`` so
    copied fields cannot drift (#447). Tool arguments never override these.

    Attributes:
        workspace_id: Trusted workspace from resolved access caller.
        profile_id: Access-profile id.
        project_id: Trusted project binding (never from client args).
        allowlist: Tool ids the profile may use.
        user_id: Acting principal id from resolved access caller.
    """

    workspace_id: str
    profile_id: str
    project_id: str
    allowlist: frozenset[str]
    user_id: str = ""

    @classmethod
    def from_access_caller(
        cls,
        access_caller: ProjectAccessCaller,
        *,
        profile_id: str,
        project_id: str,
        allowlist: frozenset[str],
    ) -> McpCallerContext:
        """Build context from a membership-verified ``ProjectAccessCaller``."""
        return cls(
            workspace_id=access_caller.workspace_id,
            profile_id=profile_id,
            project_id=project_id,
            allowlist=allowlist,
            user_id=access_caller.principal.user_id,
        )


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
        """Return True when *tool_id* is contributed, pack-enabled, allowlisted, and isolation-safe."""
        if tool_id not in self.tool_pack:
            return False
        if tool_id not in caller.allowlist:
            return False
        if not is_isolation_safe(tool_id):
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
