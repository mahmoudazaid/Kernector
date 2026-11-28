"""Acceptance: auth before factories / catalog / OAuth / mutations (#447)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from composition.auth import build_auth_store, clear_auth_store_cache
from presentation.http.app import create_app
from presentation.http import deps as http_deps
from presentation.http.deps import get_settings

_ORIGIN = "http://localhost:3000"

_ROUTE_INVENTORY = (
    ("GET", "/api/v1/documents"),
    ("GET", "/api/v1/projects"),
    ("POST", "/api/v1/chat/ask"),
    ("GET", "/api/v1/connectors/google-drive"),
    ("GET", "/api/v1/connectors/google-drive/oauth/start"),
    ("GET", "/api/v1/connectors/github"),
    ("GET", "/api/v1/connectors/github/oauth/start"),
    ("GET", "/api/v1/connectors/jira"),
    ("GET", "/api/v1/connectors/jira/oauth/start"),
    ("POST", "/api/v1/test-design/drafts"),
)


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


@pytest.mark.parametrize(("method", "path"), _ROUTE_INVENTORY)
def test_route_inventory_denies_unauthenticated(
    auth_env, method: str, path: str
) -> None:
    client = _client()
    response = client.request(
        method,
        path,
        json={"query": "x"} if method == "POST" and "chat" in path else None,
    )
    if method == "POST" and "test-design" in path:
        response = client.post(path, json={})
    assert response.status_code == 401, f"{method} {path}: {response.text}"


def test_denial_before_document_catalog_factory(auth_env, monkeypatch) -> None:
    calls: list[str] = []

    def _boom():
        calls.append("catalog")
        raise AssertionError("catalog must not build before auth")

    monkeypatch.setattr(http_deps, "get_document_catalog", _boom)
    client = _client()
    response = client.get("/api/v1/documents")
    assert response.status_code == 401
    assert calls == []


def test_denial_before_oauth_start_without_membership(auth_env, monkeypatch) -> None:
    calls: list[str] = []

    def _boom(*_a, **_k):
        calls.append("oauth")
        raise AssertionError("oauth must not start before membership")

    monkeypatch.setattr(
        "presentation.http.deps.start_google_drive_oauth", _boom
    )
    client = _client()
    store = build_auth_store(get_settings())
    store.create_user("alice", "secret-password")
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "secret-password"},
        headers={"Origin": _ORIGIN},
    )
    assert login.status_code == 200
    response = client.get("/api/v1/connectors/google-drive/oauth/start")
    assert response.status_code == 403
    assert calls == []


def test_foreign_project_is_sanitized_404(auth_env) -> None:
    client = _client()
    store = build_auth_store(get_settings())
    user = store.create_user("alice", "secret-password")
    store.grant_membership(user.user_id, "test-workspace")
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "secret-password"},
        headers={"Origin": _ORIGIN},
    )
    assert login.status_code == 200
    response = client.get("/api/v1/projects/prj_foreign")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
