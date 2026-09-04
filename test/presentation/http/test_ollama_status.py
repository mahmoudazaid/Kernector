"""Ollama status probe HTTP adapter — probe stubbed; no live Ollama."""

from fastapi.testclient import TestClient

from application.runtime_settings import ProbeOllamaStatus
from presentation.http.app import create_app
from presentation.http.deps import get_probe_ollama_status


def test_ollama_status_returns_reachable_models() -> None:
    app = create_app()
    app.dependency_overrides[get_probe_ollama_status] = lambda: ProbeOllamaStatus(
        probe=lambda _url: {"reachable": True, "models": ["llama3.2"]}
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/ollama/status",
        params={"base_url": "http://127.0.0.1:11434"},
    )

    assert response.status_code == 200
    assert response.json() == {"reachable": True, "models": ["llama3.2"]}


def test_ollama_status_returns_unreachable() -> None:
    app = create_app()
    app.dependency_overrides[get_probe_ollama_status] = lambda: ProbeOllamaStatus(
        probe=lambda _url: {"reachable": False, "models": []}
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/ollama/status",
        params={"base_url": "http://127.0.0.1:11434"},
    )

    assert response.status_code == 200
    assert response.json() == {"reachable": False, "models": []}


def test_ollama_status_rejects_blank_base_url() -> None:
    app = create_app()
    app.dependency_overrides[get_probe_ollama_status] = lambda: ProbeOllamaStatus(
        probe=lambda _url: {"reachable": True, "models": []}
    )
    client = TestClient(app)

    response = client.get("/api/v1/ollama/status", params={"base_url": "  "})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert response.headers["content-type"].startswith("application/problem+json")


def test_openapi_includes_ollama_status_path() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    assert "/api/v1/ollama/status" in schema["paths"]
    props = schema["components"]["schemas"]["OllamaStatusResponse"]["properties"]
    assert {"reachable", "models"} <= set(props)
