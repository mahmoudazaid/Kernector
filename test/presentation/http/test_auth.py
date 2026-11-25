"""HTTP auth routes (#182)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from composition.auth import build_auth_store, clear_auth_store_cache
from presentation.http.app import create_app
from presentation.http.deps import get_settings

_PROBLEM = "application/problem+json"
_ORIGIN = "http://localhost:3000"


@pytest.fixture
def auth_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clear_auth_store_cache()
    get_settings.cache_clear()
    monkeypatch.setenv("AUTH_SQL_PATH", str(tmp_path / "auth.sqlite"))
    monkeypatch.setenv("AUTH_CSRF_KEY", "test-csrf-key-32-bytes-long!!!!")
    monkeypatch.setenv("AUTH_TRUSTED_ORIGINS", _ORIGIN)
    monkeypatch.setenv("AUTH_LOGIN_MAX_FAILURES", "3")
    monkeypatch.setenv("AUTH_LOGIN_LOCKOUT_SECONDS", "600")
    monkeypatch.setenv("AUTH_SESSION_TTL_SECONDS", "3600")
    yield
    clear_auth_store_cache()
    get_settings.cache_clear()


def _client() -> TestClient:
    return TestClient(create_app(cors_origins=()), raise_server_exceptions=False)


def _provision(username: str = "alice", password: str = "secret-password") -> None:
    store = build_auth_store(get_settings())
    store.create_user(username, password)


def test_login_requires_trusted_origin(auth_env) -> None:
    _provision()
    client = _client()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "secret-password"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.headers["content-type"].startswith(_PROBLEM)


def test_login_success_sets_cookie_and_csrf(auth_env) -> None:
    _provision()
    client = _client()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "secret-password"},
        headers={"Origin": _ORIGIN},
    )
    assert response.status_code == 200, response.text
    assert response.headers.get("cache-control") == "no-store"
    body = response.json()
    assert body["username"] == "alice"
    assert body["user_id"].startswith("usr_")
    assert body["csrf_token"]
    assert "secret-password" not in response.text
    assert client.cookies.get("kernector_session")


def test_me_restores_same_csrf_without_rotation(auth_env) -> None:
    _provision()
    client = _client()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "secret-password"},
        headers={"Origin": _ORIGIN},
    )
    csrf = login.json()["csrf_token"]
    user_id = login.json()["user_id"]
    first = client.get("/api/v1/auth/me")
    second = client.get("/api/v1/auth/me")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["csrf_token"] == csrf
    assert second.json()["csrf_token"] == csrf
    assert first.json()["user_id"] == user_id
    assert first.headers.get("cache-control") == "no-store"


def test_login_generic_failure_and_lockout(auth_env) -> None:
    _provision()
    client = _client()
    for _ in range(3):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "wrong"},
            headers={"Origin": _ORIGIN},
        )
        assert response.status_code == 401
        assert response.json()["code"] == "unauthorized"
        assert "wrong" not in response.text
        assert "alice" not in response.json().get("detail", "").lower()
    # locked — even correct password fails generically
    locked = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "secret-password"},
        headers={"Origin": _ORIGIN},
    )
    assert locked.status_code == 401


def test_logout_requires_csrf_and_invalidates(auth_env) -> None:
    _provision()
    client = _client()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "secret-password"},
        headers={"Origin": _ORIGIN},
    )
    csrf = login.json()["csrf_token"]
    denied = client.post("/api/v1/auth/logout")
    assert denied.status_code == 403
    ok = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf},
    )
    assert ok.status_code == 204
    assert ok.headers.get("cache-control") == "no-store"
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 401


def test_user_id_stable_across_relogin(auth_env) -> None:
    _provision()
    client = _client()
    first = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "secret-password"},
        headers={"Origin": _ORIGIN},
    )
    user_id = first.json()["user_id"]
    client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": first.json()["csrf_token"]},
    )
    second = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "secret-password"},
        headers={"Origin": _ORIGIN},
    )
    assert second.json()["user_id"] == user_id
    assert second.json()["csrf_token"] != first.json()["csrf_token"]
