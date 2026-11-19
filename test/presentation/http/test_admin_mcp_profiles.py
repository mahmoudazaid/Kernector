"""Admin MCP profile and tools HTTP API (#324 Slice F)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from presentation.http.app import create_app
from presentation.http.deps import get_settings

_PROBLEM = "application/problem+json"
_ADMIN = {"Authorization": "Bearer admin-secret-token"}


@pytest.fixture(autouse=True)
def _admin_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin-secret-token")
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "ws-a")
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("DOCUMENT_CATALOG_BACKEND", "sql")
    monkeypatch.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client() -> TestClient:
    return TestClient(create_app(cors_origins=()), raise_server_exceptions=False)


def _create_project(client: TestClient) -> str:
    response = client.post("/api/v1/projects", json={"name": "Alpha", "slug": "alpha"})
    assert response.status_code == 201, response.text
    return response.json()["project_id"]


def test_list_tools_marks_core_pack_unavailable_and_side_effect() -> None:
    client = _client()
    response = client.get("/api/v1/admin/mcp/tools", headers=_ADMIN)
    assert response.status_code == 200, response.text
    tools = {item["tool_id"]: item for item in response.json()["tools"]}
    search = tools["core.search_knowledge"]
    assert search["kind"] == "core"
    assert search["allowlistable"] is False
    assert search["unavailable_reason"]
    project_list = tools["core.project_list"]
    assert project_list["allowlistable"] is True
    assert project_list["side_effecting"] is False
    # Pack side-effect example when contributed
    xray = tools.get("software_delivery.create_xray_tests")
    if xray is not None:
        assert xray["kind"] == "pack"
        assert xray["side_effecting"] is True


def test_create_list_get_rotate_allowlist_revoke_profile() -> None:
    client = _client()
    project_id = _create_project(client)

    created = client.post(
        "/api/v1/admin/mcp/profiles",
        headers=_ADMIN,
        json={"project_id": project_id, "name": "cursor-dev"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["plaintext_token"]
    profile_id = body["profile"]["profile_id"]
    assert body["profile"]["allowlist"] == []
    assert "plaintext_token" not in body["profile"]
    token = body["plaintext_token"]

    listed = client.get("/api/v1/admin/mcp/profiles", headers=_ADMIN)
    assert listed.status_code == 200
    assert listed.json()[0]["profile_id"] == profile_id
    assert "plaintext_token" not in listed.text

    got = client.get(f"/api/v1/admin/mcp/profiles/{profile_id}", headers=_ADMIN)
    assert got.status_code == 200
    assert token not in got.text

    allow = client.put(
        f"/api/v1/admin/mcp/profiles/{profile_id}/allowlist",
        headers=_ADMIN,
        json={"allowlist": ["core.project_list"]},
    )
    assert allow.status_code == 200, allow.text
    assert allow.json()["allowlist"] == ["core.project_list"]

    blocked = client.put(
        f"/api/v1/admin/mcp/profiles/{profile_id}/allowlist",
        headers=_ADMIN,
        json={"allowlist": ["core.search_knowledge"]},
    )
    assert blocked.status_code == 422
    assert blocked.headers["content-type"].startswith(_PROBLEM)

    rotated = client.post(
        f"/api/v1/admin/mcp/profiles/{profile_id}/rotate",
        headers=_ADMIN,
    )
    assert rotated.status_code == 200
    assert rotated.json()["plaintext_token"]
    assert rotated.json()["plaintext_token"] != token

    revoked = client.post(
        f"/api/v1/admin/mcp/profiles/{profile_id}/revoke",
        headers=_ADMIN,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
