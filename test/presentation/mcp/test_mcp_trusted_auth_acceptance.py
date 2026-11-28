"""MCP acceptance: legacy-null fail-closed and no tool-arg workspace override (#447)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from application.mcp_access.profiles import (
    CreateAccessProfile,
    CreateAccessProfileRequest,
)
from composition.auth import build_auth_store, clear_auth_store_cache
from composition.mcp.tool_registry import McpToolRegistry
from domain.mcp_access.models import McpAccessProfileStatus
from domain.project.models import Project
from infrastructure.config import require_mcp_settings_from_env
from infrastructure.mcp_access.sql_store import SqlMcpAccessProfileStore
from infrastructure.project.sql_store import SqlProjectStore
from presentation.http.deps import get_settings
from presentation.mcp.app import create_mcp_app


@pytest.fixture
def mcp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clear_auth_store_cache()
    get_settings.cache_clear()
    catalog = tmp_path / "catalog.sqlite"
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "testserver,127.0.0.1:8000,localhost:8000")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "")
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "ws-a")
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", str(catalog))
    monkeypatch.setenv("AUTH_SQL_PATH", str(tmp_path / "auth.sqlite"))
    monkeypatch.setenv("AUTH_CSRF_KEY", "test-csrf-key-32-bytes-long!!!!")
    yield catalog
    clear_auth_store_cache()
    get_settings.cache_clear()


def _member_user(workspace_id: str, project_id: str) -> str:
    auth = build_auth_store(get_settings())
    user = auth.create_user("mcp-alice", "secret-password")
    auth.grant_membership(user.user_id, workspace_id)
    auth.grant_project(user.user_id, workspace_id, project_id)
    return user.user_id


def test_legacy_null_user_id_profile_is_rejected(mcp_env: Path) -> None:
    catalog = mcp_env
    with SqlProjectStore(catalog, "ws-a").transaction() as tx:
        tx.projects.add(Project("prj_alpha", "Alpha", "alpha", 1))
    user_id = _member_user("ws-a", "prj_alpha")
    store = SqlMcpAccessProfileStore(catalog, "ws-a")
    created = CreateAccessProfile(store=store).execute(
        CreateAccessProfileRequest(
            user_id=user_id, project_id="prj_alpha", name="legacy"
        )
    )
    # Simulate legacy null user_id row (migration 012 nullable).
    store.update(replace(created.profile, user_id=None))

    app = create_mcp_app(
        mcp_settings=require_mcp_settings_from_env(),
        registry=McpToolRegistry(contributions=(), enabled_packs=()),
        workspace_id="ws-a",
    )
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {created.plaintext_token}"},
        )
    assert response.status_code == 401


def test_tool_arguments_cannot_override_trusted_workspace(mcp_env: Path) -> None:
    """Profile workspace stays trusted; foreign workspace in args is ignored."""
    from composition.mcp.access import current_caller
    from composition.mcp.tool_registry import McpToolContribution

    catalog = mcp_env
    with SqlProjectStore(catalog, "ws-a").transaction() as tx:
        tx.projects.add(Project("prj_alpha", "Alpha", "alpha", 1))
    user_id = _member_user("ws-a", "prj_alpha")
    store = SqlMcpAccessProfileStore(catalog, "ws-a")
    created = CreateAccessProfile(store=store).execute(
        CreateAccessProfileRequest(
            user_id=user_id, project_id="prj_alpha", name="cursor"
        )
    )
    seen: list[str] = []

    class _EchoTool:
        name = "core.project_list"
        args_schema = None
        output_schema = None

        def run(self, arguments: dict) -> str:
            caller = current_caller()
            assert caller is not None
            seen.append(caller.workspace_id)
            _ = arguments.get("workspace_id")
            return caller.workspace_id

    store.update(
        replace(
            created.profile,
            allowlist=frozenset({"core.project_list"}),
            status=McpAccessProfileStatus.ACTIVE,
        )
    )
    registry = McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id="core.project_list",
                pack_id=None,
                factory=lambda: _EchoTool(),
            ),
        ),
        enabled_packs=(),
    )
    app = create_mcp_app(
        mcp_settings=require_mcp_settings_from_env(),
        registry=registry,
        workspace_id="ws-a",
    )
    headers = {
        "Authorization": f"Bearer {created.plaintext_token}",
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
        session = {**headers, "mcp-session-id": init.headers["mcp-session-id"]}
        client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=session,
        )
        called = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "core_project_list",
                    "arguments": {"workspace_id": "ws_foreign"},
                },
            },
            headers=session,
        )
    assert called.status_code == 200, called.text
    assert seen == ["ws-a"]
