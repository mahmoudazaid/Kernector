"""Slice 0–1: MCP architecture bridge, auth, hosts, empty discovery."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from mcp import Client
from starlette.testclient import TestClient

from composition.mcp_access import (
    FixedCallerContextResolver,
    MissingCallerContextError,
    McpCallerContext,
    RequestScopedCallerContextResolver,
)
from composition.mcp_tool_registry import McpToolRegistry
from infrastructure.config import require_mcp_settings_from_env
from presentation.mcp.app import BearerAuthMiddleware, build_mcp_server, create_mcp_app


@pytest.fixture
def mcp_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token-secret")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "127.0.0.1:8000,localhost:8000")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "http://127.0.0.1:8000")
    monkeypatch.setenv("MCP_ACCESS_PROFILE", "default")
    monkeypatch.setenv("MCP_TOOL_ALLOWLIST", "")
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "ws-test")
    yield


def test_require_mcp_settings_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "localhost:8000")
    with pytest.raises(ValueError, match="MCP_AUTH_TOKEN"):
        require_mcp_settings_from_env()


def test_require_mcp_settings_requires_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_AUTH_TOKEN", "tok")
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
    with pytest.raises(ValueError, match="MCP_ALLOWED_HOSTS"):
        require_mcp_settings_from_env()


def test_require_mcp_settings_rejects_host_wildcard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_AUTH_TOKEN", "tok")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "example.com:*")
    with pytest.raises(ValueError, match="wildcard"):
        require_mcp_settings_from_env()


def test_require_mcp_settings_rejects_duplicate_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_AUTH_TOKEN", "tok")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "a,a")
    with pytest.raises(ValueError, match="duplicate"):
        require_mcp_settings_from_env()


def test_request_scoped_resolver_fails_closed_without_state() -> None:
    resolver = RequestScopedCallerContextResolver()
    with pytest.raises(MissingCallerContextError):
        resolver.resolve(None)


def test_streamable_http_app_builds(mcp_env: None) -> None:
    registry = McpToolRegistry(contributions=(), enabled_packs=())
    caller = McpCallerContext(
        workspace_id="ws-test",
        profile_id="default",
        allowlist=frozenset(),
    )
    server = build_mcp_server(
        registry=registry,
        resolver=FixedCallerContextResolver(caller),
    )
    app = server.streamable_http_app(streamable_http_path="/mcp")
    assert app is not None


@pytest.mark.anyio
async def test_protocol_client_lists_empty_when_allowlist_empty() -> None:
    registry = McpToolRegistry(contributions=(), enabled_packs=())
    caller = McpCallerContext(
        workspace_id="ws-test",
        profile_id="default",
        allowlist=frozenset(),
    )
    server = build_mcp_server(
        registry=registry,
        resolver=FixedCallerContextResolver(caller),
    )
    async with Client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
        assert tools.tools == []


def test_healthz_is_public(mcp_env: None) -> None:
    registry = McpToolRegistry(contributions=(), enabled_packs=())
    from composition.mcp_settings import load_mcp_settings
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.routing import Route
    from presentation.mcp.app import _healthz

    mcp_cfg = load_mcp_settings()
    caller = McpCallerContext("ws-test", "default", frozenset())
    server = build_mcp_server(
        registry=registry,
        resolver=RequestScopedCallerContextResolver(),
    )
    raw = server.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(mcp_cfg.allowed_hosts),
            allowed_origins=list(mcp_cfg.allowed_origins),
        ),
        custom_starlette_routes=[Route("/healthz", endpoint=_healthz)],
    )
    app = BearerAuthMiddleware(
        raw,
        auth_token=mcp_cfg.auth_token,
        caller_factory=lambda: caller,
    )
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mcp_requires_bearer(mcp_env: None) -> None:
    registry = McpToolRegistry(contributions=(), enabled_packs=())
    caller = McpCallerContext("ws-test", "default", frozenset())
    server = build_mcp_server(
        registry=registry,
        resolver=RequestScopedCallerContextResolver(),
    )
    from composition.mcp_settings import load_mcp_settings
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.routing import Route
    from presentation.mcp.app import _healthz

    mcp_cfg = load_mcp_settings()
    raw = server.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(mcp_cfg.allowed_hosts),
            allowed_origins=list(mcp_cfg.allowed_origins),
        ),
        custom_starlette_routes=[Route("/healthz", endpoint=_healthz)],
    )
    app = BearerAuthMiddleware(
        raw,
        auth_token=mcp_cfg.auth_token,
        caller_factory=lambda: caller,
    )
    client = TestClient(app)
    response = client.post("/mcp", json={})
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
