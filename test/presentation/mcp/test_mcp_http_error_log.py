"""Failed MCP POSTs log the JSON-RPC method so 4xx floods are diagnosable."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from composition.mcp.access import McpCallerContext
from presentation.mcp.app import BearerAuthMiddleware

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "MCP-Protocol-Version": "2026-07-28"}


async def _echo(request: Request) -> JSONResponse:
    body = await request.json()
    status = 404 if body.get("method") == "missing/method" else 200
    return JSONResponse({"echo": body}, status_code=status)


def _client() -> TestClient:
    inner = Starlette(routes=[Route("/mcp", _echo, methods=["POST"])])
    app = BearerAuthMiddleware(
        inner,
        auth_token=TOKEN,
        caller_factory=lambda: McpCallerContext("ws", "default", frozenset()),
    )
    return TestClient(app)


def test_failed_post_logs_method_protocol_and_session_presence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="presentation.mcp.app")
    body = {"jsonrpc": "2.0", "id": 1, "method": "missing/method", "params": {"secret": "s3"}}

    response = _client().post("/mcp", json=body, headers=HEADERS)

    assert response.status_code == 404
    assert response.json() == {"echo": body}
    assert (
        "mcp_http_error status=404 method=missing/method protocol=2026-07-28 session=no"
        in caplog.text
    )
    assert "s3" not in caplog.text


def test_successful_post_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING", logger="presentation.mcp.app")

    response = _client().post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=HEADERS
    )

    assert response.status_code == 200
    assert "mcp_http_error" not in caplog.text


@pytest.mark.parametrize(
    ("body", "logged"),
    [
        (b'[{"jsonrpc":"2.0","method":"missing/method"}]', "method=batch"),
        (b'{"jsonrpc":"2.0","id":1,"method":"missing/method\\n<x>"}', "method=invalid"),
        (b'{"jsonrpc":"2.0","id":1,"result":{}}', "method=response"),
        (b"not json", "method=invalid"),
    ],
)
def test_untrusted_method_values_are_never_logged_verbatim(
    caplog: pytest.LogCaptureFixture, body: bytes, logged: str
) -> None:
    caplog.set_level("WARNING", logger="presentation.mcp.app")

    async def _not_found(_request: Request) -> JSONResponse:
        return JSONResponse({}, status_code=404)

    inner = Starlette(routes=[Route("/mcp", _not_found, methods=["POST"])])
    app = BearerAuthMiddleware(
        inner,
        auth_token=TOKEN,
        caller_factory=lambda: McpCallerContext("ws", "default", frozenset()),
    )

    TestClient(app).post(
        "/mcp", content=body, headers={**HEADERS, "Content-Type": "application/json"}
    )

    assert logged in caplog.text
    assert "<x>" not in caplog.text
