"""Admin MCP management API auth (#324 Slice A)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infrastructure.config import require_admin_api_token_from_env
from presentation.http.app import create_app

_PROBLEM = "application/problem+json"
_SERVER = "/api/v1/admin/mcp/server"


def _client() -> TestClient:
    return TestClient(create_app(cors_origins=()), raise_server_exceptions=False)


def test_require_admin_api_token_fails_closed_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    with pytest.raises(ValueError, match="ADMIN_API_TOKEN"):
        require_admin_api_token_from_env()


def test_admin_mcp_server_rejects_missing_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin-secret-token")
    response = _client().get(_SERVER)
    assert response.status_code == 401
    assert response.headers["content-type"].startswith(_PROBLEM)
    body = response.json()
    assert body["code"] == "unauthorized"
    assert "admin-secret-token" not in response.text
    assert response.headers.get("www-authenticate") == "Bearer"


def test_admin_mcp_server_rejects_wrong_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin-secret-token")
    response = _client().get(
        _SERVER, headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
    assert "admin-secret-token" not in response.text
    assert "wrong-token" not in response.text


def test_admin_mcp_server_accepts_valid_admin_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin-secret-token")
    response = _client().get(
        _SERVER, headers={"Authorization": "Bearer admin-secret-token"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auth_mode"] == "profile-bearer"
    assert body["transport"] == "streamable-http"
    assert "admin-secret-token" not in response.text
