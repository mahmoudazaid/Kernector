"""HTTP trusted workspace context and auth-before-work (#447)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from composition.auth import build_auth_store, clear_auth_store_cache
from presentation.http.app import create_app
from presentation.http.deps import get_settings

_ORIGIN = "http://localhost:3000"


@pytest.fixture
def auth_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clear_auth_store_cache()
    get_settings.cache_clear()
    monkeypatch.setenv("AUTH_SQL_PATH", str(tmp_path / "auth.sqlite"))
    monkeypatch.setenv("AUTH_CSRF_KEY", "test-csrf-key-32-bytes-long!!!!")
    monkeypatch.setenv("AUTH_TRUSTED_ORIGINS", _ORIGIN)
    yield
    clear_auth_store_cache()
    get_settings.cache_clear()


def _client() -> TestClient:
    return TestClient(create_app(cors_origins=()), raise_server_exceptions=False)


def _login_with_membership(client: TestClient, *, workspace_id: str = "test-workspace") -> None:
    store = build_auth_store(get_settings())
    user = store.create_user("alice", "secret-password")
    store.grant_membership(user.user_id, workspace_id)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "secret-password"},
        headers={"Origin": _ORIGIN},
    )
    assert response.status_code == 200, response.text


def test_documents_require_authentication(auth_env) -> None:
    client = _client()
    response = client.get("/api/v1/documents")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_documents_require_membership(auth_env) -> None:
    client = _client()
    store = build_auth_store(get_settings())
    store.create_user("alice", "secret-password")
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "secret-password"},
        headers={"Origin": _ORIGIN},
    )
    assert login.status_code == 200
    response = client.get("/api/v1/documents")
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_documents_succeed_with_membership(auth_env) -> None:
    client = _client()
    _login_with_membership(client)
    response = client.get("/api/v1/documents")
    assert response.status_code == 200, response.text


def test_projects_require_authentication(auth_env) -> None:
    client = _client()
    response = client.get("/api/v1/projects")
    assert response.status_code == 401


def test_chat_ask_requires_authentication(auth_env) -> None:
    client = _client()
    response = client.post("/api/v1/chat/ask", json={"query": "hello"})
    assert response.status_code == 401


def test_connector_status_requires_authentication(auth_env) -> None:
    client = _client()
    for path in (
        "/api/v1/connectors/google-drive",
        "/api/v1/connectors/github",
        "/api/v1/connectors/jira",
    ):
        response = client.get(path)
        assert response.status_code == 401, path


def test_documents_deny_when_trusted_workspace_differs_from_process_bound(
    auth_env,
) -> None:
    """Until #448, membership in another workspace cannot unlock this process."""
    client = _client()
    _login_with_membership(client, workspace_id="other-workspace")
    response = client.get("/api/v1/documents")
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
