"""Settings dependency resolves once per process (``lru_cache`` on ``get_settings``)."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from application.runtime_settings import (
    GetRuntimeSettings,
    RuntimeConstraints,
    RuntimeSettingsDefaults,
)
from composition import Settings
from presentation.http import deps
from presentation.http.app import create_app
from presentation.http.deps import get_settings


def test_get_settings_calls_load_runtime_settings_once(monkeypatch) -> None:
    calls: list[object] = []
    sentinel = SimpleNamespace(
        provider="openrouter",
        domain_tools=SimpleNamespace(enabled_packs=()),
    )

    def _load() -> SimpleNamespace:
        calls.append(object())
        return sentinel

    monkeypatch.setattr(deps, "load_runtime_settings", _load)

    first = get_settings()
    second = get_settings()

    assert first is sentinel
    assert second is sentinel
    assert len(calls) == 1


def test_settings_uses_cached_settings_across_requests(monkeypatch) -> None:
    calls: list[int] = []
    sentinel = SimpleNamespace(
        provider="ollama",
        domain_tools=SimpleNamespace(enabled_packs=()),
    )

    def _load() -> SimpleNamespace:
        calls.append(1)
        return sentinel

    def _build(settings: SimpleNamespace) -> GetRuntimeSettings:
        assert settings is sentinel
        return GetRuntimeSettings(
            providers=("ollama",),
            defaults=RuntimeSettingsDefaults(
                provider="ollama",
                openrouter_models=(),
                openrouter_default_model=None,
                ollama_default_base_url=None,
                ollama_default_model=None,
                enabled_packs=(),
                constraints=RuntimeConstraints(
                    max_input_length=10_000,
                    max_upload_bytes=5_242_880,
                    supported_upload_suffixes=(".md",),
                ),
            ),
        )

    monkeypatch.setattr(deps, "load_runtime_settings", _load)
    monkeypatch.setattr(deps, "build_runtime_settings", _build)
    client = TestClient(create_app())

    assert client.get("/api/v1/settings").status_code == 200
    assert client.get("/api/v1/settings").status_code == 200
    assert len(calls) == 1


def test_get_settings_returns_real_settings_after_mocked_tests(
    monkeypatch,
) -> None:
    """Cache must not leak SimpleNamespace sentinels into later tests."""
    monkeypatch.delenv("HTTP_DEV_CORS", raising=False)
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert isinstance(settings.provider, str)
    assert settings.provider
