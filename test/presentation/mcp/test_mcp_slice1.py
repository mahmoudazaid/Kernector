"""Slice 0–1: MCP architecture bridge, auth, hosts, empty discovery."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from mcp import Client
from starlette.testclient import TestClient

from application.mcp_access.profiles import (
    CreateAccessProfile,
    CreateAccessProfileRequest,
)
from composition.mcp.access import (
    FixedCallerContextResolver,
    MissingCallerContextError,
    McpCallerContext,
    RequestScopedCallerContextResolver,
)
from composition.mcp.tool_registry import McpToolRegistry
from domain.project.models import Project
from infrastructure.config import require_mcp_settings_from_env
from infrastructure.mcp_access.sql_store import SqlMcpAccessProfileStore
from infrastructure.project.sql_store import SqlProjectStore
from presentation.mcp.app import BearerAuthMiddleware, build_mcp_server, create_mcp_app

_CALLER = McpCallerContext("ws-test", "default", "prj_test", frozenset())


@pytest.fixture
def mcp_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "127.0.0.1:8000,localhost:8000")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "http://127.0.0.1:8000")
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "ws-test")
    yield


def _fixed_auth(caller: McpCallerContext = _CALLER):
    def authenticate(presented: str) -> McpCallerContext | None:
        return caller if presented == "test-token-secret" else None

    return authenticate


def test_require_mcp_settings_requires_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
    with pytest.raises(ValueError, match="MCP_ALLOWED_HOSTS"):
        require_mcp_settings_from_env()


def test_require_mcp_settings_rejects_host_wildcard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "example.com:*")
    with pytest.raises(ValueError, match="wildcard"):
        require_mcp_settings_from_env()


def test_require_mcp_settings_rejects_origin_wildcard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "localhost:8000")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://app.example.com:*")
    with pytest.raises(ValueError, match="wildcard"):
        require_mcp_settings_from_env()


def test_require_mcp_settings_rejects_duplicate_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "a,a")
    with pytest.raises(ValueError, match="duplicate"):
        require_mcp_settings_from_env()


def test_request_scoped_resolver_fails_closed_without_state() -> None:
    resolver = RequestScopedCallerContextResolver()
    with pytest.raises(MissingCallerContextError):
        resolver.resolve(None)


def test_streamable_http_app_builds(mcp_env: None) -> None:
    registry = McpToolRegistry(contributions=(), enabled_packs=())
    server = build_mcp_server(
        registry=registry,
        resolver=FixedCallerContextResolver(_CALLER),
    )
    app = server.streamable_http_app(streamable_http_path="/mcp")
    assert app is not None


@pytest.mark.anyio
async def test_protocol_client_lists_empty_when_allowlist_empty() -> None:
    registry = McpToolRegistry(contributions=(), enabled_packs=())
    server = build_mcp_server(
        registry=registry,
        resolver=FixedCallerContextResolver(_CALLER),
    )
    async with Client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
        assert tools.tools == []


def test_healthz_is_public(mcp_env: None) -> None:
    registry = McpToolRegistry(contributions=(), enabled_packs=())
    from composition.mcp.settings import load_mcp_settings
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.routing import Route
    from presentation.mcp.app import _healthz

    mcp_cfg = load_mcp_settings()
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
    app = BearerAuthMiddleware(raw, authenticate=_fixed_auth())
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_public_discovery_routes_are_not_404(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """GET / and CDP probes must not 404 on the hosted MCP port."""
    from composition.mcp.settings import load_mcp_settings

    catalog = tmp_path / "catalog.sqlite"
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "")
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "ws-test")
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", str(catalog))
    with SqlProjectStore(catalog, "ws-test").transaction() as tx:
        tx.projects.add(Project("prj_test", "Test", "test", 1))
    app = create_mcp_app(
        mcp_settings=load_mcp_settings(),
        registry=McpToolRegistry(contributions=(), enabled_packs=()),
        workspace_id="ws-test",
    )
    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert root.json()["mcp"] == "/mcp"
        assert root.json()["healthz"] == "/healthz"

        cdp = client.get("/json/version")
        assert cdp.status_code == 200
        body = cdp.json()
        assert body["error"] == "not_chrome_devtools"
        assert "webSocketDebuggerUrl" not in body

        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}


def test_mcp_requires_bearer(mcp_env: None) -> None:
    registry = McpToolRegistry(contributions=(), enabled_packs=())
    server = build_mcp_server(
        registry=registry,
        resolver=RequestScopedCallerContextResolver(),
    )
    from composition.mcp.settings import load_mcp_settings
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
    app = BearerAuthMiddleware(raw, authenticate=_fixed_auth())
    client = TestClient(app)
    response = client.post("/mcp", json={})
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.anyio
async def test_mcp_non_ascii_bearer_returns_401_not_500(mcp_env: None) -> None:
    """Non-ASCII Authorization must 401 without raising into a 500."""
    from composition.mcp.settings import load_mcp_settings
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.routing import Route
    from presentation.mcp.app import _healthz

    registry = McpToolRegistry(contributions=(), enabled_packs=())
    mcp_cfg = load_mcp_settings()
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
    app = BearerAuthMiddleware(raw, authenticate=_fixed_auth())
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"authorization", b"Bearer \x80"),
            (b"host", b"localhost:8000"),
        ],
        "client": ("127.0.0.1", 123),
        "server": ("localhost", 8000),
        "state": {},
    }
    messages: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 401
    header_map = {k.lower(): v for k, v in start["headers"]}
    assert header_map[b"www-authenticate"] == b"Bearer"


def test_authenticated_http_lists_project_list_via_request_scoped_caller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Pin middleware → request.state.mcp_caller → RequestScopedCallerContextResolver."""
    import json
    import re
    from dataclasses import replace

    from application.project.projects import ListProjects
    from composition.mcp.project_list import TOOL_NAME as PROJECT_LIST
    from composition.mcp.project_list import ProjectListTool
    from composition.mcp.settings import load_mcp_settings
    from composition.mcp.tool_registry import McpToolContribution

    catalog = tmp_path / "catalog.sqlite"
    monkeypatch.setenv(
        "MCP_ALLOWED_HOSTS", "testserver,127.0.0.1:8000,localhost:8000"
    )
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "")
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "ws-test")
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", str(catalog))

    projects = SqlProjectStore(catalog, "ws-test")
    with projects.transaction() as tx:
        tx.projects.add(Project("prj_test", "Test", "test", 1))
    store = SqlMcpAccessProfileStore(catalog, "ws-test")
    created = CreateAccessProfile(store=store).execute(
        CreateAccessProfileRequest(project_id="prj_test", name="dev")
    )
    profile = replace(
        created.profile,
        allowlist=frozenset({PROJECT_LIST}),
        updated_at=created.profile.updated_at,
    )
    store.update(profile)

    registry = McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id=PROJECT_LIST,
                pack_id=None,
                factory=lambda: ProjectListTool(ListProjects(store=projects)),
            ),
        ),
        enabled_packs=(),
    )
    app = create_mcp_app(
        mcp_settings=load_mcp_settings(),
        registry=registry,
        workspace_id="ws-test",
    )
    headers = {
        "Authorization": f"Bearer {created.plaintext_token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    with TestClient(app, raise_server_exceptions=True) as client:
        init = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
            headers=headers,
        )
        assert init.status_code == 200
        session_id = init.headers.get("mcp-session-id")
        assert session_id
        session_headers = {**headers, "mcp-session-id": session_id}
        notified = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=session_headers,
        )
        assert notified.status_code == 202
        listed = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers=session_headers,
        )
        assert listed.status_code == 200
        match = re.search(r"data:\s*(\{.*\})", listed.text)
        assert match is not None
        payload = json.loads(match.group(1))
        names = [tool["name"] for tool in payload["result"]["tools"]]
        assert names == ["core_project_list"]


def _stream_test_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> object:
    from composition.mcp.settings import load_mcp_settings

    catalog = tmp_path / "catalog.sqlite"
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "")
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "ws-test")
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", str(catalog))
    with SqlProjectStore(catalog, "ws-test").transaction() as tx:
        tx.projects.add(Project("prj_test", "Test", "test", 1))
    store = SqlMcpAccessProfileStore(catalog, "ws-test")
    created = CreateAccessProfile(store=store).execute(
        CreateAccessProfileRequest(project_id="prj_test", name="dev")
    )
    app = create_mcp_app(
        mcp_settings=load_mcp_settings(),
        registry=McpToolRegistry(contributions=(), enabled_packs=()),
        workspace_id="ws-test",
    )
    return app, created.plaintext_token


def test_authenticated_get_mcp_declines_standalone_sse_stream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No server-initiated messages: GET /mcp is 405, so no stream blocks shutdown."""
    app, token = _stream_test_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.get(
            "/mcp",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "text/event-stream",
            },
        )
    assert response.status_code == 405
    assert response.headers.get("allow") == "POST, DELETE"


def test_unauthenticated_get_mcp_is_still_401(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app, _token = _stream_test_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.get("/mcp", headers={"Accept": "text/event-stream"})
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
