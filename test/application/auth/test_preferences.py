"""Preference catalog validation (#182)."""

from __future__ import annotations

from application.auth.preferences import (
    catalog_allows_pair,
    project_preferences,
)
from application.runtime_settings import (
    OllamaSettingsView,
    OpenRouterSettingsView,
    RuntimeConstraints,
    RuntimeSettingsCatalog,
)


def _catalog(
    *,
    providers: tuple[str, ...] = ("openrouter", "ollama"),
    openrouter_models: tuple[str, ...] = ("model-a",),
    openrouter_default: str | None = "model-a",
    ollama_default: str | None = "llama3",
) -> RuntimeSettingsCatalog:
    return RuntimeSettingsCatalog(
        providers=providers,
        default_provider="openrouter",
        openrouter=OpenRouterSettingsView(
            models=openrouter_models, default_model=openrouter_default
        ),
        ollama=OllamaSettingsView(
            default_base_url="http://127.0.0.1:11434",
            default_model=ollama_default,
        ),
        model_settings=(),
        enabled_packs=(),
        constraints=RuntimeConstraints(
            max_input_length=1000,
            max_upload_bytes=1000,
            supported_upload_suffixes=(".md",),
        ),
    )


def test_catalog_allows_known_openrouter_pair() -> None:
    catalog = _catalog()
    assert catalog_allows_pair(catalog, "openrouter", "model-a") is True
    assert catalog_allows_pair(catalog, "openrouter", "missing") is False


def test_project_preferences_missing_and_stale() -> None:
    catalog = _catalog()
    missing = project_preferences(catalog, provider=None, model=None)
    assert missing.usable is False
    stale = project_preferences(
        catalog, provider="openrouter", model="gone"
    )
    assert stale.usable is False
    assert stale.model == "gone"
    ok = project_preferences(
        catalog, provider="openrouter", model="model-a"
    )
    assert ok.usable is True
