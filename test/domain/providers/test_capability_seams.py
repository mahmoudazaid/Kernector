"""Offline contracts for advertised non-purpose capabilities (#462)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from domain.model_settings import SETTINGS, defaults
from domain.providers import capabilities_for, known_providers
from infrastructure.config import OllamaSettings, OpenRouterSettings
from infrastructure.llm.ollama import OllamaChat, probe_ollama
from infrastructure.llm.openrouter import OpenRouterChat


class _RecordingChat:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    def __call__(self, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError("should not invoke")


class _RecordingFactory:
    def __init__(self) -> None:
        self.config: OpenRouterSettings | None = None
        self.settings: Mapping[str, object] | None = None
        self.chat = _RecordingChat()

    def __call__(
        self, config: OpenRouterSettings, settings: Mapping[str, object]
    ) -> _RecordingChat:
        self.config = config
        self.settings = settings
        return self.chat


def test_openrouter_custom_base_url_reaches_factory() -> None:
    factory = _RecordingFactory()
    config = OpenRouterSettings(
        api_key="sk-test",
        base_url="https://custom.example/v1",
        model="chat/model",
        models=(),
        embedding_model="embed",
        rewrite_model="rewrite",
        timeout=30.0,
    )
    chat = OpenRouterChat(config, model_factory=factory)
    # Trigger factory without completing the chain successfully.
    with pytest.raises(Exception):
        chat.complete("sys", (), {"temperature": 0.1})
    assert factory.config is not None
    assert factory.config.base_url == "https://custom.example/v1"


def test_ollama_custom_base_url_override_reaches_adapter() -> None:
    config = OllamaSettings(
        base_url="http://configured:11434",
        model="llama3.2",
        timeout=30.0,
    )
    chat = OllamaChat(config)
    assert chat._base_url == "http://configured:11434"


def test_ollama_model_discovery_probe_uses_injected_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"models": [{"name": "llama3.2:latest"}]}

    def _get(url: str, **_kwargs: object) -> _Resp:
        calls.append(url)
        return _Resp()

    monkeypatch.setattr("infrastructure.llm.ollama.requests.get", _get)
    result = probe_ollama("http://127.0.0.1:11434", timeout=1.0)
    assert result == {"reachable": True, "models": ["llama3.2:latest"]}
    assert calls == ["http://127.0.0.1:11434/api/tags"]


def test_deferred_model_discovery_stays_false() -> None:
    for provider in ("openrouter", "openai", "anthropic", "gemini"):
        assert capabilities_for(provider).model_discovery is False


def test_parameters_match_model_settings_for_every_provider() -> None:
    for provider in known_providers():
        advertised = capabilities_for(provider).parameters
        from_settings = {
            setting.key for setting in SETTINGS if provider in setting.providers
        }
        assert advertised == frozenset(from_settings)
        assert set(defaults(provider)) == from_settings


def test_openrouter_complete_passes_only_caller_settings_through_factory() -> None:
    factory = _RecordingFactory()
    config = OpenRouterSettings(
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
        model="chat/model",
        models=(),
        embedding_model="embed",
        rewrite_model="rewrite",
        timeout=30.0,
    )
    chat = OpenRouterChat(config, model_factory=factory)
    allowed = {"temperature": 0.2, "max_tokens": 100, "top_p": 0.9}
    with pytest.raises(Exception):
        chat.complete("sys", (), allowed)
    assert factory.settings == allowed
