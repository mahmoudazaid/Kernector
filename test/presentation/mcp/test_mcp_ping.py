"""Clients keep sending ``ping`` on 2026-07-28, which dropped it; it must not answer 404."""

from __future__ import annotations

import pytest
from mcp import Client
from mcp.server.transport_security import TransportSecuritySettings
from starlette.testclient import TestClient

from composition.mcp.access import FixedCallerContextResolver, McpCallerContext
from composition.mcp.tool_registry import McpToolRegistry
from presentation.mcp.app import build_mcp_server

MODERN = "2026-07-28"


def _server():
    caller = McpCallerContext(workspace_id="ws-test", profile_id="default", allowlist=frozenset())
    return build_mcp_server(
        registry=McpToolRegistry(contributions=(), enabled_packs=()),
        resolver=FixedCallerContextResolver(caller),
    )


def _post(client: TestClient, method: str) -> tuple[int, dict]:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": MODERN,
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        },
    }
    response = client.post(
        "/mcp",
        json=body,
        headers={
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MODERN,
            "Mcp-Method": method,
        },
    )
    return response.status_code, response.json()


def test_modern_ping_answers_an_empty_result() -> None:
    app = _server().streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    with TestClient(app) as client:
        status, payload = _post(client, "ping")
        unknown_status, _ = _post(client, "missing/method")

    assert status == 200
    assert payload["result"]["resultType"] == "complete"
    assert "error" not in payload
    assert unknown_status == 404


@pytest.mark.anyio
@pytest.mark.filterwarnings("ignore:ping is removed")
async def test_legacy_ping_still_uses_the_sdk_handler() -> None:
    async with Client(_server(), raise_exceptions=True, mode="legacy") as client:
        await client.send_ping()
