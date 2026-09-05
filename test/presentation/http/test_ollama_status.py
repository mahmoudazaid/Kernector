"""Ollama status probe HTTP adapter — probe stubbed; no live Ollama."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from application.runtime_settings import ProbeOllamaStatus
from presentation.http.app import create_app
from presentation.http.deps import get_probe_ollama_status, get_settings


def _settings(*, ollama_base_url: str | None = "http://127.0.0.1:11434") -> SimpleNamespace:
    return SimpleNamespace(
        provider="ollama",
        ollama=SimpleNamespace(base_url=ollama_base_url, model="llama3.2", timeout=1.0),
        openrouter=SimpleNamespace(model=None, models=()),
        domain_tools=SimpleNamespace(enabled_packs=()),
    )


def test_ollama_status_returns_reachable_models() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _settings()
    app.dependency_overrides[get_probe_ollama_status] = lambda: ProbeOllamaStatus(
        probe=lambda url: {"reachable": True, "models": ["llama3.2"]}
        if url == "http://127.0.0.1:11434"
        else {"reachable": False, "models": []}
    )
    client = TestClient(app)

    response = client.get("/api/v1/ollama/status")

    assert response.status_code == 200
    assert response.json() == {"reachable": True, "models": ["llama3.2"]}


def test_ollama_status_returns_unreachable() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _settings()
    app.dependency_overrides[get_probe_ollama_status] = lambda: ProbeOllamaStatus(
        probe=lambda _url: {"reachable": False, "models": []}
    )
    client = TestClient(app)

    response = client.get("/api/v1/ollama/status")

    assert response.status_code == 200
    assert response.json() == {"reachable": False, "models": []}


def test_ollama_status_conflicts_when_base_url_unconfigured() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _settings(ollama_base_url=None)
    probed: list[str] = []
    app.dependency_overrides[get_probe_ollama_status] = lambda: ProbeOllamaStatus(
        probe=lambda url: probed.append(url) or {"reachable": True, "models": []}
    )
    client = TestClient(app)

    response = client.get("/api/v1/ollama/status")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "ollama_unconfigured"
    assert "not configured" in body["detail"].lower()
    assert response.headers["content-type"].startswith("application/problem+json")
    assert probed == []


def test_ollama_status_ignores_client_supplied_base_url() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _settings(
        ollama_base_url="http://127.0.0.1:11434"
    )
    seen: list[str] = []
    app.dependency_overrides[get_probe_ollama_status] = lambda: ProbeOllamaStatus(
        probe=lambda url: seen.append(url) or {"reachable": True, "models": ["llama3.2"]}
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/ollama/status",
        params={"base_url": "http://evil.example/"},
    )

    assert response.status_code == 200
    assert seen == ["http://127.0.0.1:11434"]


def test_openapi_includes_ollama_status_path() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    assert "/api/v1/ollama/status" in schema["paths"]
    operation = schema["paths"]["/api/v1/ollama/status"]["get"]
    assert "parameters" not in operation or operation.get("parameters") in (None, [])
    props = schema["components"]["schemas"]["OllamaStatusResponse"]["properties"]
    assert {"reachable", "models"} <= set(props)
