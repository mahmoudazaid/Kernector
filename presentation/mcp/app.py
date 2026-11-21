"""Streamable HTTP MCP presentation adapter (low-level Server)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping
from typing import Any

import anyio.from_thread
import anyio.to_thread
from mcp import MCPError, types
from mcp_types.version import is_version_at_least
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.lowlevel.server import Server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from composition.mcp.access import (
    CallerContextResolver,
    MissingCallerContextError,
    McpCallerContext,
    RequestScopedCallerContextResolver,
)
from composition.mcp.settings import McpSettings, load_mcp_settings
from composition.mcp.tool_registry import (
    McpInvokeResult,
    McpPromptArgumentError,
    McpToolDescriptor,
    McpToolPrompt,
    McpToolRegistry,
    TOOL_UNAVAILABLE_CODE,
)
from domain.tool_approval import ApprovalDeferredError, PendingToolApproval

logger = logging.getLogger(__name__)

SERVER_INSTRUCTIONS = (
    "Kernector never reads your workspace or disk. When a Kernector tool takes "
    "file paths and file content, read the files yourself and send each "
    "workspace-relative path with the file's exact, unmodified text. Use the "
    "prompts this server lists to start its guided workflows."
)

# No WWW-Authenticate: Cursor treats that challenge as OAuth and aborts
# createClient with ``Canceled`` instead of retrying static Bearer.
_UNAUTHORIZED = JSONResponse(
    {"detail": "Unauthorized"},
    status_code=401,
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


def _to_mcp_prompt(prompt: McpToolPrompt) -> types.Prompt:
    return types.Prompt(
        name=prompt.name,
        description=prompt.description,
        arguments=[
            types.PromptArgument(
                name=prompt.argument,
                description=prompt.argument_description,
                required=False,
            )
        ],
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
    lines.extend(f"- {item}" for item in pending.item_titles)
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


class _ApprovalInputRequired(ApprovalDeferredError):
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
        # Mid-call elicitation needs a request back-channel (SSE POST response).
        # JSON-response mode sets can_send_request=False — fall through to
        # InputRequiredResult instead of raising NoBackChannelError.
        if not self._input_required and self._ctx.session.can_send_request:
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


# Public paths that never require a profile bearer (discovery / probes).
_PUBLIC_PATHS = frozenset({"/", "/healthz", "/json/version"})

# When MCP_ALLOWED_ORIGINS is empty, the MCP SDK still rejects *present*
# Origins that are not in the allowlist. Cursor sends ``Origin: null`` or
# ``vscode-webview://cursor`` on initialize — those must be allowed for local
# Streamable HTTP or the client aborts with ``Canceled``.
_DEFAULT_LOCAL_ORIGINS: tuple[str, ...] = (
    "null",
    "vscode-webview://cursor",
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
)


def _effective_allowed_origins(configured: tuple[str, ...]) -> list[str]:
    """Return Origin allowlist for transport security.

    Empty env means local Cursor-safe defaults (not “reject every Origin”).
    Explicit ``MCP_ALLOWED_ORIGINS`` still wins for locked-down deployments.
    """
    if configured:
        return list(configured)
    return list(_DEFAULT_LOCAL_ORIGINS)


def _is_well_known(path: str) -> bool:
    """OAuth discovery probes must 404 without a bearer challenge."""
    return "/.well-known/" in path or path.startswith("/.well-known/")


def _scope_headers(scope: Scope) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_key, raw_val in scope.get("headers") or []:
        try:
            out[raw_key.decode("latin-1").lower()] = raw_val.decode("latin-1")
        except Exception:
            continue
    return out


class BearerAuthMiddleware:
    """Require a profile bearer for ``/mcp``; leave discovery routes public.

    Pure ASGI (not ``BaseHTTPMiddleware``) so Streamable HTTP responses are not
    buffered — Cursor's client cancels when the initialize stream is held.
    Authenticated ``GET /mcp`` gets 405: the server offers no standalone SSE
    stream, which the MCP Streamable HTTP spec allows.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        authenticate: Callable[[str], McpCallerContext | None],
        mcp_path: str = "/mcp",
    ) -> None:
        self.app = app
        self._authenticate = authenticate
        self._mcp_path = mcp_path.rstrip("/") or "/mcp"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = (scope.get("path") or "/").rstrip("/") or "/"
        headers = _scope_headers(scope)
        method = scope.get("method") or "GET"

        if path in _PUBLIC_PATHS or _is_well_known(path):
            await self.app(scope, receive, send)
            return
        if path != self._mcp_path and not path.startswith(f"{self._mcp_path}/"):
            await self.app(scope, receive, send)
            return

        header = headers.get("authorization")
        if header is None or not header.lower().startswith("bearer "):
            await _UNAUTHORIZED(scope, receive, send)
            return
        presented = header[7:].strip()
        try:
            caller = self._authenticate(presented)
        except Exception:
            logger.exception("mcp_profile_auth_failed")
            await _UNAUTHORIZED(scope, receive, send)
            return
        if caller is None:
            await _UNAUTHORIZED(scope, receive, send)
            return
        if method == "GET":
            # No server-initiated messages; an idle SSE stream would block
            # graceful shutdown until a forced second Ctrl+C.
            await _NO_STANDALONE_STREAM(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        if not isinstance(state, dict):
            state = {}
            scope["state"] = state
        state["mcp_caller"] = caller

        if method != "POST":
            await self.app(scope, receive, send)
            return

        # Eagerly buffer the body so error logs work even when the downstream
        # handler never reads the request (and so we can replay it once).
        # http.disconnect must exit: uvicorn returns it immediately with no
        # await, so ``continue`` busy-loops and starves the event loop.
        body_chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body_chunks.append(message.get("body", b"") or b"")
            if not message.get("more_body", False):
                break
        body = b"".join(body_chunks)
        replayed = False
        rpc_method = _jsonrpc_method(body)

        async def receive_replay() -> dict[str, Any]:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        status_box: dict[str, int] = {"code": 0}

        async def send_wrapped(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_box["code"] = int(message.get("status") or 0)
            await send(message)

        await self.app(scope, receive_replay, send_wrapped)
        if status_box["code"] >= 400:
            logger.warning(
                "mcp_http_error status=%s method=%s protocol=%s session=%s",
                status_box["code"],
                rpc_method,
                _log_token(headers.get("mcp-protocol-version")),
                "yes" if headers.get("mcp-session-id") else "no",
            )


_LOGGABLE_TOKEN = re.compile(r"[A-Za-z0-9_./-]{1,64}")


def _log_token(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, str) and _LOGGABLE_TOKEN.fullmatch(value):
        return value
    return "invalid"


def _jsonrpc_method(body: bytes) -> str:
    try:
        message = json.loads(body)
    except ValueError:
        return "invalid"
    if isinstance(message, list):
        return "batch"
    if not isinstance(message, dict):
        return "invalid"
    if "method" not in message:
        return "response"
    return _log_token(message["method"])


async def _healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def _root(_request: Request) -> JSONResponse:
    """Public discovery so ``GET /`` is not a confusing 404."""
    return JSONResponse(
        {
            "service": "kernector-mcp",
            "status": "ok",
            "mcp": "/mcp",
            "healthz": "/healthz",
            "auth": "profile-bearer",
        }
    )


async def _not_chrome_devtools(_request: Request) -> JSONResponse:
    """Answer Chrome DevTools probes on this port without a 404 access log.

    Cursor (and similar) probe listening ports with ``GET /json/version``.
    This is Kernector MCP, not CDP — omit ``webSocketDebuggerUrl`` so probes
    fail closed without treating the process as Chrome.
    """
    return JSONResponse(
        {
            "error": "not_chrome_devtools",
            "message": "This is Kernector MCP, not a Chrome DevTools endpoint.",
            "mcp": "/mcp",
            "healthz": "/healthz",
        }
    )


async def _answer_modern_ping(
    ctx: ServerRequestContext[Any], call_next: CallNext
) -> HandlerResult:
    """Answer ``ping`` on 2026-07-28, which dropped it; clients still send it as a keepalive."""
    if ctx.method == "ping" and is_version_at_least(
        ctx.protocol_version or "", _INPUT_REQUIRED_VERSION
    ):
        return {"resultType": "complete"}
    return await call_next(ctx)


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

    async def on_list_prompts(
        ctx: ServerRequestContext[Any],
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListPromptsResult:
        try:
            caller = resolver.resolve(ctx.request)
        except MissingCallerContextError:
            logger.warning("mcp_list_prompts_missing_caller")
            return types.ListPromptsResult(prompts=[])
        prompts = await anyio.to_thread.run_sync(registry.list_prompts, caller)
        return types.ListPromptsResult(prompts=[_to_mcp_prompt(item) for item in prompts])

    async def on_get_prompt(
        ctx: ServerRequestContext[Any],
        params: types.GetPromptRequestParams,
    ) -> types.GetPromptResult:
        try:
            caller = resolver.resolve(ctx.request)
        except MissingCallerContextError:
            logger.warning("mcp_get_prompt_missing_caller")
            raise MCPError(types.INVALID_PARAMS, "Unknown prompt") from None
        try:
            text = await anyio.to_thread.run_sync(
                registry.get_prompt, caller, params.name, params.arguments
            )
        except McpPromptArgumentError:
            raise MCPError(types.INVALID_PARAMS, "Invalid prompt arguments") from None
        if text is None:
            raise MCPError(types.INVALID_PARAMS, "Unknown prompt")
        return types.GetPromptResult(
            messages=[
                types.PromptMessage(
                    role="user", content=types.TextContent(type="text", text=text)
                )
            ]
        )

    # Clients poll these even when unadvertised; "Method not found" maps to HTTP 404.
    async def on_list_resources(
        _ctx: ServerRequestContext[Any],
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[])

    async def on_list_resource_templates(
        _ctx: ServerRequestContext[Any],
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(resource_templates=[])

    server = Server(
        name,
        version="0.1.0",
        instructions=SERVER_INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_prompts=on_list_prompts,
        on_get_prompt=on_get_prompt,
        on_list_resources=on_list_resources,
        on_list_resource_templates=on_list_resource_templates,
    )
    server.middleware.append(_answer_modern_ping)
    return server


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

    catalog_path = runtime.document_catalog.sql_path
    if catalog_path is None:
        raise ValueError(
            "DOCUMENT_CATALOG_SQL_PATH is required for MCP profile authentication"
        )

    def _authenticate(presented: str) -> McpCallerContext | None:
        from composition.mcp_access.container import authenticate_mcp_profile_token

        profile = authenticate_mcp_profile_token(catalog_path, presented)
        if profile is None:
            return None
        if profile.workspace_id != bound_workspace:
            return None
        return McpCallerContext(
            workspace_id=profile.workspace_id,
            profile_id=profile.profile_id,
            project_id=profile.project_id,
            allowlist=profile.allowlist,
        )

    active_resolver = resolver or RequestScopedCallerContextResolver()
    server = build_mcp_server(registry=registry, resolver=active_resolver)

    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(mcp_cfg.allowed_hosts),
        allowed_origins=_effective_allowed_origins(mcp_cfg.allowed_origins),
    )
    # json_response=True: Cursor's Streamable HTTP client fails to parse
    # text/event-stream initialize/tools/list. Mid-call elicitation is
    # unavailable in this mode; _ElicitationGate falls back to InputRequiredResult.
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        transport_security=transport_security,
        custom_starlette_routes=[
            Route("/", endpoint=_root),
            Route("/healthz", endpoint=_healthz),
            Route("/json/version", endpoint=_not_chrome_devtools),
        ],
    )
    return BearerAuthMiddleware(app, authenticate=_authenticate)


# ASGI entry for uvicorn presentation.mcp.app:app — built lazily on first import
# only when MCP env is configured; tests call create_mcp_app explicitly.
def __getattr__(name: str) -> Any:
    if name == "app":
        return create_mcp_app()
    raise AttributeError(name)
