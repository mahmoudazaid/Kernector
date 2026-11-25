"""HTTP preferences routes (#182)."""

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
    monkeypatch.setenv("OPENROUTER_MODELS", "model-a,model-b")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    yield
    clear_auth_store_cache()
    get_settings.cache_clear()


def _client() -> TestClient:
    return TestClient(create_app(cors_origins=()), raise_server_exceptions=False)


def _login(client: TestClient) -> str:
    store = build_auth_store(get_settings())
    store.create_user("alice", "secret-password")
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "secret-password"},
        headers={"Origin": _ORIGIN},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def test_preferences_require_auth(auth_env) -> None:
    client = _client()
    response = client.get("/api/v1/me/preferences")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_preferences_missing_then_put_get(auth_env) -> None:
    client = _client()
    csrf = _login(client)
    empty = client.get("/api/v1/me/preferences")
    assert empty.status_code == 200
    assert empty.json()["usable"] is False
    assert empty.headers.get("cache-control") == "no-store"

    denied = client.put(
        "/api/v1/me/preferences",
        json={"provider": "openrouter", "model": "model-a"},
    )
    assert denied.status_code == 403

    saved = client.put(
        "/api/v1/me/preferences",
        json={"provider": "openrouter", "model": "model-a"},
        headers={"X-CSRF-Token": csrf},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "provider": "openrouter",
        "model": "model-a",
        "usable": True,
    }

    got = client.get("/api/v1/me/preferences")
    assert got.json()["usable"] is True
    assert got.json()["model"] == "model-a"


def test_preferences_reject_unknown_pair(auth_env) -> None:
    client = _client()
    csrf = _login(client)
    response = client.put(
        "/api/v1/me/preferences",
        json={"provider": "openrouter", "model": "not-in-catalog"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_preferences"
