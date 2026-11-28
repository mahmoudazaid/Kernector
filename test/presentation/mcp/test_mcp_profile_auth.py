"""MCP bearer auth via access-profile tokens (#324 Slice D)."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from application.mcp_access.profiles import (
    CreateAccessProfile,
    CreateAccessProfileRequest,
    RevokeAccessProfile,
)
from composition.mcp.tool_registry import McpToolRegistry
from domain.project.models import Project
from infrastructure.config import require_mcp_settings_from_env
from infrastructure.mcp_access.sql_store import SqlMcpAccessProfileStore
from infrastructure.project.sql_store import SqlProjectStore
from presentation.mcp.app import create_mcp_app


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    return tmp_path / "catalog.sqlite"


@pytest.fixture
def mcp_hosts(
    monkeypatch: pytest.MonkeyPatch, catalog_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "testserver,127.0.0.1:8000,localhost:8000")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "")
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "ws-a")
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", str(catalog_path))
    monkeypatch.setenv("AUTH_SQL_PATH", str(tmp_path / "auth.sqlite"))
    monkeypatch.setenv("AUTH_CSRF_KEY", "test-csrf-key-32-bytes-long!!!!")
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_TOOL_ALLOWLIST", raising=False)
    monkeypatch.delenv("MCP_ACCESS_PROFILE", raising=False)


def _seed_profile(catalog_path: Path) -> str:
    from composition.auth import build_auth_store, clear_auth_store_cache
    from presentation.http.deps import get_settings

    clear_auth_store_cache()
    get_settings.cache_clear()
    projects = SqlProjectStore(catalog_path, "ws-a")
    with projects.transaction() as tx:
        tx.projects.add(Project("prj_alpha", "Alpha", "alpha", 1))
    auth = build_auth_store(get_settings())
    user = auth.create_user("mcp-alice", "secret-password")
    auth.grant_membership(user.user_id, "ws-a")
    auth.grant_project(user.user_id, "ws-a", "prj_alpha")
    store = SqlMcpAccessProfileStore(catalog_path, "ws-a")
    created = CreateAccessProfile(store=store).execute(
        CreateAccessProfileRequest(
            user_id=user.user_id, project_id="prj_alpha", name="cursor"
        )
    )
    return created.plaintext_token


def test_require_mcp_settings_no_longer_requires_shared_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "localhost:8000")
    settings = require_mcp_settings_from_env()
    assert settings.allowed_hosts == ("localhost:8000",)
    assert not hasattr(settings, "auth_token") or getattr(
        settings, "auth_token", None
    ) in (None, "")


def test_legacy_mcp_auth_token_does_not_authenticate(
    monkeypatch: pytest.MonkeyPatch,
    catalog_path: Path,
    mcp_hosts: None,
) -> None:
    monkeypatch.setenv("MCP_AUTH_TOKEN", "legacy-shared-secret")
    _seed_profile(catalog_path)
    app = create_mcp_app(
        mcp_settings=require_mcp_settings_from_env(),
        registry=McpToolRegistry(contributions=(), enabled_packs=()),
        workspace_id="ws-a",
    )
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": "Bearer legacy-shared-secret"},
        )
    assert response.status_code == 401


def test_profile_token_authenticates_and_revocation_closes_session(
    monkeypatch: pytest.MonkeyPatch,
    catalog_path: Path,
    mcp_hosts: None,
) -> None:
    token = _seed_profile(catalog_path)
    app = create_mcp_app(
        mcp_settings=require_mcp_settings_from_env(),
        registry=McpToolRegistry(contributions=(), enabled_packs=()),
        workspace_id="ws-a",
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    with TestClient(app) as client:
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
        assert init.status_code == 200, init.text

        store = SqlMcpAccessProfileStore(catalog_path, "ws-a")
        profiles = store.list()
        assert len(profiles) == 1
        RevokeAccessProfile(store=store).execute(profiles[0].profile_id)

        denied = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers=headers,
        )
        assert denied.status_code == 401
