"""CORS defaults for the HTTP presentation adapter."""

import pytest
from fastapi.testclient import TestClient

from presentation.http.app import create_app, cors_origins_from_env

_ORIGIN = "http://localhost:3000"


@pytest.fixture(autouse=True)
def _neutralize_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)


def test_dev_cors_allows_configured_origin(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_DEV_CORS", "true")
    monkeypatch.setenv("HTTP_CORS_ORIGINS", _ORIGIN)
    assert cors_origins_from_env() == (_ORIGIN,)

    client = TestClient(create_app(cors_origins=(_ORIGIN,)))
    response = client.options(
        "/health",
        headers={
            "Origin": _ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers.get("access-control-allow-origin") == _ORIGIN


def test_create_app_reads_cors_from_env_when_origins_omitted(monkeypatch) -> None:
    """Module-level ``app = create_app()`` takes the ``cors_origins is None`` branch."""
    monkeypatch.setenv("HTTP_DEV_CORS", "on")
    monkeypatch.setenv("HTTP_CORS_ORIGINS", _ORIGIN)

    client = TestClient(create_app())
    headers = {
        "Origin": _ORIGIN,
        "Access-Control-Request-Method": "GET",
    }
    preflight = client.options("/health", headers=headers)
    get_health = client.get("/health", headers={"Origin": _ORIGIN})

    assert preflight.headers.get("access-control-allow-origin") == _ORIGIN
    assert get_health.status_code == 200
    assert get_health.headers.get("access-control-allow-origin") == _ORIGIN


def test_create_app_installs_no_cors_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("HTTP_DEV_CORS", raising=False)
    monkeypatch.delenv("HTTP_CORS_ORIGINS", raising=False)

    client = TestClient(create_app())
    response = client.get("/health", headers={"Origin": _ORIGIN})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_production_cors_has_empty_allowlist(monkeypatch) -> None:
    monkeypatch.delenv("HTTP_DEV_CORS", raising=False)
    monkeypatch.delenv("HTTP_CORS_ORIGINS", raising=False)
    assert cors_origins_from_env() == ()

    client = TestClient(create_app(cors_origins=()))
    response = client.options(
        "/health",
        headers={
            "Origin": _ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_cors_does_not_echo_disallowed_origin() -> None:
    client = TestClient(create_app(cors_origins=(_ORIGIN,)))
    response = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers.get("access-control-allow-origin") != "https://evil.example"


def test_cors_preflight_allows_post() -> None:
    client = TestClient(create_app(cors_origins=(_ORIGIN,)))
    response = client.options(
        "/api/v1/chat/ask",
        headers={
            "Origin": _ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.headers.get("access-control-allow-origin") == _ORIGIN
    allow_methods = response.headers.get("access-control-allow-methods", "")
    assert "POST" in allow_methods.upper()
