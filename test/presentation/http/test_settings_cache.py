"""Settings dependency resolves once per process (matches Streamlit cache_resource)."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

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


def test_capabilities_uses_cached_settings_across_requests(monkeypatch) -> None:
    calls: list[int] = []
    sentinel = SimpleNamespace(
        provider="ollama",
        domain_tools=SimpleNamespace(enabled_packs=()),
    )

    def _load() -> SimpleNamespace:
        calls.append(1)
        return sentinel

    monkeypatch.setattr(deps, "load_runtime_settings", _load)
    client = TestClient(create_app())

    assert client.get("/api/v1/capabilities").status_code == 200
    assert client.get("/api/v1/capabilities").status_code == 200
    assert len(calls) == 1


def test_get_settings_returns_real_settings_after_mocked_tests(
    monkeypatch,
) -> None:
    """Cache must not leak SimpleNamespace sentinels into later tests."""
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("HTTP_DEV_CORS", raising=False)
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert isinstance(settings.provider, str)
    assert settings.provider
