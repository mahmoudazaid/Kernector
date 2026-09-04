"""Runtime settings catalog HTTP adapter — deps overridden; no live providers."""

from fastapi.testclient import TestClient

from application.runtime_settings import GetRuntimeSettings, RuntimeSettingsDefaults
from presentation.http.app import create_app
from presentation.http.deps import get_runtime_settings


def test_settings_returns_runtime_catalog() -> None:
    app = create_app()
    app.dependency_overrides[get_runtime_settings] = lambda: GetRuntimeSettings(
        providers=("openrouter", "ollama"),
        defaults=RuntimeSettingsDefaults(
            provider="openrouter",
            openrouter_models=("openai/gpt-4o-mini",),
            openrouter_default_model="openai/gpt-4o-mini",
            ollama_default_base_url="http://127.0.0.1:11434",
            ollama_default_model="llama3.2",
        ),
    )
    client = TestClient(app)

    response = client.get("/api/v1/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["providers"] == ["openrouter", "ollama"]
    assert body["default_provider"] == "openrouter"
    assert body["openrouter"] == {
        "models": ["openai/gpt-4o-mini"],
        "default_model": "openai/gpt-4o-mini",
    }
    assert body["ollama"] == {
        "default_base_url": "http://127.0.0.1:11434",
        "default_model": "llama3.2",
    }
    assert [s["key"] for s in body["model_settings"]] == [
        "temperature",
        "max_tokens",
        "top_p",
    ]
    assert body["model_settings"][0]["default"] == 0.3
    assert body["model_settings"][0]["providers"] == ["openrouter", "ollama"]


def test_openapi_includes_settings_path() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    assert "/api/v1/settings" in schema["paths"]
    props = schema["components"]["schemas"]["RuntimeSettingsResponse"]["properties"]
    assert {
        "providers",
        "default_provider",
        "openrouter",
        "ollama",
        "model_settings",
    } <= set(props)
