"""Runtime settings catalog — providers, defaults, and model-settings defs."""

import pytest

from application.errors import ApplicationValidationError
from application.runtime_settings import (
    GetRuntimeSettings,
    ProbeOllamaStatus,
    RuntimeSettingsDefaults,
)


def test_get_runtime_settings_assembles_catalog_from_defaults_and_domain() -> None:
    use_case = GetRuntimeSettings(
        providers=("openrouter", "ollama"),
        defaults=RuntimeSettingsDefaults(
            provider="ollama",
            openrouter_models=("openai/gpt-4o-mini", "anthropic/claude-3.5"),
            openrouter_default_model="openai/gpt-4o-mini",
            ollama_default_base_url="http://127.0.0.1:11434",
            ollama_default_model="llama3.2",
        ),
    )

    catalog = use_case.execute()

    assert catalog.providers == ("openrouter", "ollama")
    assert catalog.default_provider == "ollama"
    assert catalog.openrouter.models == ("openai/gpt-4o-mini", "anthropic/claude-3.5")
    assert catalog.openrouter.default_model == "openai/gpt-4o-mini"
    assert catalog.ollama.default_base_url == "http://127.0.0.1:11434"
    assert catalog.ollama.default_model == "llama3.2"

    keys = [s.key for s in catalog.model_settings]
    assert keys == ["temperature", "max_tokens", "top_p"]
    temperature = catalog.model_settings[0]
    assert temperature.label == "Temperature"
    assert temperature.widget == "slider"
    assert temperature.default == 0.3
    assert temperature.min_value == 0.0
    assert temperature.max_value == 2.0
    assert temperature.step == 0.1
    assert temperature.providers == ("openrouter", "ollama")


def test_get_runtime_settings_allows_null_optional_defaults() -> None:
    use_case = GetRuntimeSettings(
        providers=("openrouter",),
        defaults=RuntimeSettingsDefaults(
            provider="openrouter",
            openrouter_models=(),
            openrouter_default_model=None,
            ollama_default_base_url=None,
            ollama_default_model=None,
        ),
    )

    catalog = use_case.execute()

    assert catalog.providers == ("openrouter",)
    assert catalog.openrouter.models == ()
    assert catalog.openrouter.default_model is None
    assert catalog.ollama.default_base_url is None
    assert catalog.ollama.default_model is None


def test_probe_ollama_status_reachable_with_models() -> None:
    use_case = ProbeOllamaStatus(
        probe=lambda _url: {"reachable": True, "models": ["llama3.2", "mistral"]}
    )

    status = use_case.execute("http://127.0.0.1:11434")

    assert status.reachable is True
    assert status.models == ("llama3.2", "mistral")


def test_probe_ollama_status_unreachable() -> None:
    use_case = ProbeOllamaStatus(
        probe=lambda _url: {"reachable": False, "models": []}
    )

    status = use_case.execute("http://127.0.0.1:11434")

    assert status.reachable is False
    assert status.models == ()


def test_probe_ollama_status_rejects_blank_base_url() -> None:
    use_case = ProbeOllamaStatus(probe=lambda _url: {"reachable": True, "models": []})

    with pytest.raises(ApplicationValidationError, match="base_url"):
        use_case.execute("   ")
