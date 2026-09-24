"""Streamable HTTP MCP presentation adapter (low-level Server)."""

from __future__ import annotations

import hmac
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel.server import Server, ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from composition.mcp_access import (
    CallerContextResolver,
    MissingCallerContextError,
    McpCallerContext,
    RequestScopedCallerContextResolver,
)
from composition.mcp_settings import McpSettings, load_mcp_settings
from composition.mcp_tool_registry import (
    McpInvokeResult,
    McpToolDescriptor,
    McpToolRegistry,
    TOOL_UNAVAILABLE_CODE,
)

logger = logging.getLogger(__name__)

_UNAUTHORIZED = JSONResponse(
    {"detail": "Unauthorized"},
    status_code=401,
    headers={"WWW-Authenticate": "Bearer"},
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
        inputSchema=dict(descriptor.input_schema),
        outputSchema=(
            dict(descriptor.output_schema)
            if descriptor.output_schema is not None
            else None
        ),
    )


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Require ``Authorization: Bearer`` for ``/mcp``; leave ``/healthz`` public."""

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
    ) -> types.CallToolResult:
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
        result = await anyio.to_thread.run_sync(
            registry.invoke_authorized,
            caller,
            params.name,
            arguments,
        )
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
    from composition.mcp_settings import build_mcp_registry_for_runtime

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
