"""Streamable HTTP MCP presentation adapter (low-level Server)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import anyio.from_thread
import anyio.to_thread
from mcp import types
from mcp_types.version import is_version_at_least
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import Server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from composition.mcp.access import (
    CallerContextResolver,
    MissingCallerContextError,
    McpCallerContext,
    RequestScopedCallerContextResolver,
)
from composition.mcp.settings import McpSettings, load_mcp_settings
from composition.mcp.tool_registry import (
    McpInvokeResult,
    McpToolDescriptor,
    McpToolRegistry,
    TOOL_UNAVAILABLE_CODE,
)
from domain.tool_approval import PendingToolApproval

logger = logging.getLogger(__name__)

_UNAUTHORIZED = JSONResponse(
    {"detail": "Unauthorized"},
    status_code=401,
    headers={"WWW-Authenticate": "Bearer"},
)
_NO_STANDALONE_STREAM = JSONResponse(
    {"detail": "Method Not Allowed"},
    status_code=405,
    headers={"Allow": "POST, DELETE"},
)


def _to_call_tool_result(result: McpInvokeResult) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=result.text)],
        structured_content=dict(result.structured) if result.structured else None,
        is_error=result.is_error,
    )


def _to_mcp_tool(descriptor: McpToolDescriptor) -> types.Tool:
    return types.Tool(
        name=descriptor.name,
        description=descriptor.description,
        input_schema=dict(descriptor.input_schema),
        output_schema=(
            dict(descriptor.output_schema)
            if descriptor.output_schema is not None
            else None
        ),
    )


_INPUT_REQUIRED_VERSION = "2026-07-28"
_APPROVAL_INPUT_KEY = "kernector_approval"
_APPROVAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approve": {
            "type": "boolean",
            "title": "Approve",
            "description": "Run this tool call now.",
        }
    },
    "required": ["approve"],
}


def _approval_message(pending: PendingToolApproval) -> str:
    lines = [pending.title, pending.summary]
    if pending.destination_label:
        lines.append(f"Destination: {pending.destination_label}")
    if pending.selected_title_count is not None:
        lines.append(f"Items: {pending.selected_title_count}")
    return "\n".join(lines)


def _approved(result: object) -> bool:
    if not isinstance(result, types.ElicitResult):
        return False
    content = result.content or {}
    return result.action == "accept" and content.get("approve") is True


def _approval_binding(name: str, arguments: Mapping[str, object] | None) -> str:
    canonical = json.dumps(
        {"tool": name, "arguments": arguments or {}},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _ApprovalInputRequired(Exception):
    """Ends the first round so the handler can return an input request."""


class _ElicitationGate:
    """Approval gate called from the registry worker thread.

    Protocol >= 2026-07-28 has no mid-call back-channel: the first round
    records the prompt and fails closed, the handler answers with an
    ``InputRequiredResult``, and the retry carries the user's answer. A retry
    answer only counts when ``request_state`` matches this exact call.
    """

    def __init__(
        self,
        ctx: ServerRequestContext[Any],
        params: types.CallToolRequestParams,
        arguments: Mapping[str, object] | None,
    ) -> None:
        self._ctx = ctx
        self._binding = _approval_binding(params.name, arguments)
        self._answer = (params.input_responses or {}).get(_APPROVAL_INPUT_KEY)
        self._request_state = params.request_state
        self._input_required = is_version_at_least(
            ctx.protocol_version or "", _INPUT_REQUIRED_VERSION
        )
        self.pending: PendingToolApproval | None = None

    def __call__(self, pending: PendingToolApproval) -> bool:
        if not self._input_required:
            return anyio.from_thread.run(self._ask, pending)
        if self._answer is not None and self._request_state == self._binding:
            return _approved(self._answer)
        self.pending = pending
        raise _ApprovalInputRequired

    async def _ask(self, pending: PendingToolApproval) -> bool:
        result = await self._ctx.session.elicit_form(
            _approval_message(pending),
            _APPROVAL_SCHEMA,
            related_request_id=self._ctx.request_id,
        )
        return _approved(result)

    def input_required(self) -> types.InputRequiredResult | None:
        if self.pending is None:
            return None
        request = types.ElicitRequest(
            params=types.ElicitRequestFormParams(
                message=_approval_message(self.pending),
                requested_schema=_APPROVAL_SCHEMA,
            )
        )
        return types.InputRequiredResult(
            input_requests={_APPROVAL_INPUT_KEY: request},
            request_state=self._binding,
        )


def _elicitation_gate(
    ctx: ServerRequestContext[Any],
    params: types.CallToolRequestParams,
    arguments: Mapping[str, object] | None,
) -> _ElicitationGate | None:
    """Return an approval gate, or None when the client cannot elicit."""
    capability = types.ClientCapabilities(elicitation=types.ElicitationCapability())
    if not ctx.session.check_client_capability(capability):
        return None
    return _ElicitationGate(ctx, params, arguments)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Require ``Authorization: Bearer`` for ``/mcp``; leave ``/healthz`` public.

    Authenticated ``GET /mcp`` gets 405: the server offers no standalone SSE
    stream, which the MCP Streamable HTTP spec allows.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        auth_token: str,
        caller_factory: Callable[[], McpCallerContext],
        mcp_path: str = "/mcp",
    ) -> None:
        super().__init__(app)
        self._auth_token = auth_token
        self._caller_factory = caller_factory
        self._mcp_path = mcp_path.rstrip("/") or "/mcp"

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path.rstrip("/") or "/"
        if path == "/healthz":
            return await call_next(request)
        if path == self._mcp_path or path.startswith(f"{self._mcp_path}/"):
            header = request.headers.get("authorization")
            if header is None or not header.lower().startswith("bearer "):
                return _UNAUTHORIZED
            presented = header[7:].strip()
            # Compare as bytes: str compare_digest raises TypeError on non-ASCII
            # (latin-1-decoded header bytes >= 0x80), which would escape as 500.
            if not hmac.compare_digest(
                presented.encode("utf-8"), self._auth_token.encode("utf-8")
            ):
                return _UNAUTHORIZED
            if request.method == "GET":
                # No server-initiated messages; an idle SSE stream would block
                # graceful shutdown until a forced second Ctrl+C.
                return _NO_STANDALONE_STREAM
            request.state.mcp_caller = self._caller_factory()
        return await call_next(request)


async def _healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def build_mcp_server(
    *,
    registry: McpToolRegistry,
    resolver: CallerContextResolver,
    name: str = "kernector",
) -> Server[Any]:
    """Construct a low-level MCP Server bound to *registry* and *resolver*."""

    async def on_list_tools(
        ctx: ServerRequestContext[Any],
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        try:
            caller = resolver.resolve(ctx.request)
        except MissingCallerContextError:
            logger.warning("mcp_list_tools_missing_caller")
            return types.ListToolsResult(tools=[])
        descriptors = await anyio.to_thread.run_sync(registry.list_effective, caller)
        return types.ListToolsResult(
            tools=[_to_mcp_tool(item) for item in descriptors]
        )

    async def on_call_tool(
        ctx: ServerRequestContext[Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult | types.InputRequiredResult:
        try:
            caller = resolver.resolve(ctx.request)
        except MissingCallerContextError:
            logger.warning("mcp_call_tool_missing_caller")
            return _to_call_tool_result(
                McpInvokeResult(
                    is_error=True,
                    text='{"code":"tool_unavailable","message":"Tool unavailable"}',
                    code=TOOL_UNAVAILABLE_CODE,
                    structured={
                        "code": TOOL_UNAVAILABLE_CODE,
                        "message": "Tool unavailable",
                    },
                )
            )
        arguments: Mapping[str, object] | None
        raw_args = params.arguments
        if raw_args is None:
            arguments = None
        elif isinstance(raw_args, Mapping):
            arguments = dict(raw_args)
        else:
            arguments = {}
        gate = _elicitation_gate(ctx, params, arguments)
        result = await anyio.to_thread.run_sync(
            registry.invoke_authorized,
            caller,
            params.name,
            arguments,
            gate,
        )
        input_required = None if gate is None else gate.input_required()
        if input_required is not None:
            return input_required
        return _to_call_tool_result(result)

    return Server(
        name,
        version="0.1.0",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


def create_mcp_app(
    *,
    settings: Any | None = None,
    mcp_settings: McpSettings | None = None,
    registry: McpToolRegistry | None = None,
    resolver: CallerContextResolver | None = None,
    workspace_id: str | None = None,
) -> ASGIApp:
    """Build the Streamable HTTP MCP ASGI app with auth and ``/healthz``.

    When *registry* / *resolver* are omitted, wires them from composition using
    runtime settings. *mcp_settings* defaults to :func:`load_mcp_settings`.
    """
    from composition.container import load_runtime_settings
    from composition.mcp.settings import build_mcp_registry_for_runtime

    runtime = settings or load_runtime_settings()
    mcp_cfg = mcp_settings or load_mcp_settings()
    bound_workspace = workspace_id or runtime.document_catalog.workspace_id
    if not bound_workspace:
        raise ValueError(
            "DOCUMENT_CATALOG_WORKSPACE_ID is required for the MCP adapter"
        )

    if registry is None:
        registry = build_mcp_registry_for_runtime(runtime)

    allowlist = frozenset(mcp_cfg.tool_allowlist)

    def _caller() -> McpCallerContext:
        return McpCallerContext(
            workspace_id=bound_workspace,
            profile_id=mcp_cfg.access_profile,
            allowlist=allowlist,
        )

    active_resolver = resolver or RequestScopedCallerContextResolver()
    server = build_mcp_server(registry=registry, resolver=active_resolver)

    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(mcp_cfg.allowed_hosts),
        allowed_origins=list(mcp_cfg.allowed_origins),
    )
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=transport_security,
        custom_starlette_routes=[Route("/healthz", endpoint=_healthz)],
    )
    return BearerAuthMiddleware(
        app,
        auth_token=mcp_cfg.auth_token,
        caller_factory=_caller,
    )


# ASGI entry for uvicorn presentation.mcp.app:app — built lazily on first import
# only when MCP env is configured; tests call create_mcp_app explicitly.
def __getattr__(name: str) -> Any:
    if name == "app":
        return create_mcp_app()
    raise AttributeError(name)
