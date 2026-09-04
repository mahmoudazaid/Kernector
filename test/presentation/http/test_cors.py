"""CORS defaults for the HTTP presentation adapter."""

from fastapi.testclient import TestClient

from presentation.http.app import create_app, cors_origins_from_env


def test_dev_cors_allows_configured_origin(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_DEV_CORS", "true")
    monkeypatch.setenv("HTTP_CORS_ORIGINS", "http://localhost:3000")
    assert cors_origins_from_env() == ("http://localhost:3000",)

    client = TestClient(create_app(cors_origins=("http://localhost:3000",)))
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_production_cors_has_empty_allowlist(monkeypatch) -> None:
    monkeypatch.delenv("HTTP_DEV_CORS", raising=False)
    monkeypatch.delenv("HTTP_CORS_ORIGINS", raising=False)
    assert cors_origins_from_env() == ()

    client = TestClient(create_app(cors_origins=()))
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_cors_does_not_echo_disallowed_origin() -> None:
    client = TestClient(create_app(cors_origins=("http://localhost:3000",)))
    response = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers.get("access-control-allow-origin") != "https://evil.example"
