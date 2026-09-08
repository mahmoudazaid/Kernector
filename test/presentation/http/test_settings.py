"""Runtime settings catalog HTTP adapter — deps overridden; no live providers."""

from fastapi.testclient import TestClient

from application.runtime_settings import (
    GetRuntimeSettings,
    RuntimeConstraints,
    RuntimeSettingsDefaults,
)
from presentation.http.app import create_app
from presentation.http.deps import get_runtime_settings


def _defaults(
    *,
    provider: str = "openrouter",
    enabled_packs: tuple[str, ...] = ("software-delivery",),
    max_input_length: int = 10_000,
    max_upload_bytes: int = 5_242_880,
    supported_upload_suffixes: tuple[str, ...] = (
        ".markdown",
        ".md",
        ".pdf",
        ".txt",
    ),
) -> RuntimeSettingsDefaults:
    return RuntimeSettingsDefaults(
        provider=provider,
        openrouter_models=("openai/gpt-4o-mini",),
        openrouter_default_model="openai/gpt-4o-mini",
        ollama_default_base_url="http://127.0.0.1:11434",
        ollama_default_model="llama3.2",
        enabled_packs=enabled_packs,
        constraints=RuntimeConstraints(
            max_input_length=max_input_length,
            max_upload_bytes=max_upload_bytes,
            supported_upload_suffixes=supported_upload_suffixes,
        ),
    )


def test_settings_returns_runtime_catalog() -> None:
    app = create_app()
    app.dependency_overrides[get_runtime_settings] = lambda: GetRuntimeSettings(
        providers=("openrouter", "ollama"),
        defaults=_defaults(),
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
    max_tokens = next(s for s in body["model_settings"] if s["key"] == "max_tokens")
    assert max_tokens["default"] == 1000
    assert isinstance(max_tokens["default"], int)
    assert isinstance(max_tokens["step"], int)
    assert body["enabled_packs"] == ["software-delivery"]
    assert body["constraints"] == {
        "max_input_length": 10_000,
        "max_upload_bytes": 5_242_880,
        "supported_upload_suffixes": [".markdown", ".md", ".pdf", ".txt"],
    }
    assert "max_input_length" not in body
    assert "limits" not in body
    assert "software_delivery_tools_enabled" not in body


def test_settings_returns_empty_enabled_packs_when_none_supported() -> None:
    app = create_app()
    app.dependency_overrides[get_runtime_settings] = lambda: GetRuntimeSettings(
        providers=("openrouter",),
        defaults=_defaults(enabled_packs=()),
    )

    response = TestClient(app).get("/api/v1/settings")

    assert response.status_code == 200
    assert response.json()["enabled_packs"] == []


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
        "enabled_packs",
        "constraints",
    } <= set(props)
    assert "max_input_length" not in props
    assert "limits" not in props
    constraints = schema["components"]["schemas"]["RuntimeConstraintsResponse"][
        "properties"
    ]
    assert {
        "max_input_length",
        "max_upload_bytes",
        "supported_upload_suffixes",
    } <= set(constraints)


def test_settings_publishes_nested_constraints_for_ui_preflight() -> None:
    """UI length and upload feedback read nested constraints from settings."""
    app = create_app()
    app.dependency_overrides[get_runtime_settings] = lambda: GetRuntimeSettings(
        providers=("openrouter",),
        defaults=_defaults(
            enabled_packs=(),
            max_input_length=4_000,
            max_upload_bytes=1_024,
            supported_upload_suffixes=(".md",),
        ),
    )

    response = TestClient(app).get("/api/v1/settings")

    assert response.status_code == 200
    assert response.json()["constraints"] == {
        "max_input_length": 4_000,
        "max_upload_bytes": 1_024,
        "supported_upload_suffixes": [".md"],
    }
