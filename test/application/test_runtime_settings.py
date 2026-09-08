"""Runtime settings catalog — providers, defaults, and model-settings defs."""

import pytest

from application.errors import ApplicationValidationError
from application.runtime_settings import (
    GetRuntimeSettings,
    ProbeOllamaStatus,
    RuntimeConstraints,
    RuntimeSettingsDefaults,
)


def _defaults(
    *,
    provider: str = "ollama",
    openrouter_models: tuple[str, ...] = ("openai/gpt-4o-mini", "anthropic/claude-3.5"),
    openrouter_default_model: str | None = "openai/gpt-4o-mini",
    ollama_default_base_url: str | None = "http://127.0.0.1:11434",
    ollama_default_model: str | None = "llama3.2",
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
        openrouter_models=openrouter_models,
        openrouter_default_model=openrouter_default_model,
        ollama_default_base_url=ollama_default_base_url,
        ollama_default_model=ollama_default_model,
        enabled_packs=enabled_packs,
        constraints=RuntimeConstraints(
            max_input_length=max_input_length,
            max_upload_bytes=max_upload_bytes,
            supported_upload_suffixes=supported_upload_suffixes,
        ),
    )


def test_get_runtime_settings_assembles_catalog_from_defaults_and_domain() -> None:
    use_case = GetRuntimeSettings(
        providers=("openrouter", "ollama"),
        defaults=_defaults(),
    )

    catalog = use_case.execute()

    assert catalog.providers == ("openrouter", "ollama")
    assert catalog.default_provider == "ollama"
    assert catalog.openrouter.models == ("openai/gpt-4o-mini", "anthropic/claude-3.5")
    assert catalog.openrouter.default_model == "openai/gpt-4o-mini"
    assert catalog.ollama.default_base_url == "http://127.0.0.1:11434"
    assert catalog.ollama.default_model == "llama3.2"
    assert catalog.enabled_packs == ("software-delivery",)
    assert catalog.constraints.max_input_length == 10_000
    assert catalog.constraints.max_upload_bytes == 5_242_880
    assert catalog.constraints.supported_upload_suffixes == (
        ".markdown",
        ".md",
        ".pdf",
        ".txt",
    )

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
        defaults=_defaults(
            provider="openrouter",
            openrouter_models=(),
            openrouter_default_model=None,
            ollama_default_base_url=None,
            ollama_default_model=None,
            enabled_packs=(),
        ),
    )

    catalog = use_case.execute()

    assert catalog.providers == ("openrouter",)
    assert catalog.openrouter.models == ()
    assert catalog.openrouter.default_model is None
    assert catalog.ollama.default_base_url is None
    assert catalog.ollama.default_model is None
    assert catalog.enabled_packs == ()


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


def test_get_runtime_settings_exposes_nested_constraints() -> None:
    """UI length and upload feedback read one nested constraints object."""
    use_case = GetRuntimeSettings(
        providers=("openrouter",),
        defaults=_defaults(
            provider="openrouter",
            openrouter_models=(),
            openrouter_default_model=None,
            ollama_default_base_url=None,
            ollama_default_model=None,
            enabled_packs=(),
            max_input_length=4_000,
            max_upload_bytes=1_024,
            supported_upload_suffixes=(".md",),
        ),
    )

    catalog = use_case.execute()

    assert catalog.constraints.max_input_length == 4_000
    assert catalog.constraints.max_upload_bytes == 1_024
    assert catalog.constraints.supported_upload_suffixes == (".md",)
