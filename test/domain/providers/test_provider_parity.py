"""Independent parity between registry, builders, and model_settings (#462)."""

from __future__ import annotations

import pytest

from composition.container import (
    _CHAT_MODELS,
    available_providers,
    build_embedding_model,
)
from domain.errors import UnsupportedProviderPurposeError
from domain.model_settings import SETTINGS
from domain.providers import capabilities_for, known_providers, supports
from infrastructure.config import load_settings

# Literal expected sets — independent of registry implementation tables.
_EXPECTED_KNOWN = (
    "openrouter",
    "openai",
    "anthropic",
    "gemini",
    "ollama",
)
_EXPECTED_CHAT = frozenset(_EXPECTED_KNOWN)
_EXPECTED_EMBEDDING = frozenset({"openrouter", "openai", "gemini"})
_EXPECTED_NON_EMBEDDING = frozenset({"anthropic", "ollama"})


def test_known_providers_match_literal() -> None:
    assert known_providers() == _EXPECTED_KNOWN


def test_registry_chat_matches_available_providers_and_chat_map() -> None:
    from_registry = {p for p in known_providers() if supports(p, "chat")}
    assert from_registry == _EXPECTED_CHAT
    assert from_registry == set(available_providers())
    assert from_registry == set(_CHAT_MODELS)


def test_registry_embedding_matches_literal_and_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    settings = load_settings()

    from_registry = {p for p in known_providers() if supports(p, "embedding")}
    assert from_registry == _EXPECTED_EMBEDDING

    for provider in _EXPECTED_EMBEDDING:
        model = build_embedding_model(settings, provider=provider)
        assert model is not None

    for provider in _EXPECTED_NON_EMBEDDING:
        with pytest.raises(UnsupportedProviderPurposeError):
            build_embedding_model(settings, provider=provider)


def test_registry_parameters_match_model_settings() -> None:
    for provider in known_providers():
        advertised = capabilities_for(provider).parameters
        listed = frozenset(
            setting.key for setting in SETTINGS if provider in setting.providers
        )
        assert advertised == listed


def test_anthropic_embedding_refused_everywhere() -> None:
    assert supports("anthropic", "embedding") is False
    assert capabilities_for("anthropic").embeddings is False
    with pytest.raises(UnsupportedProviderPurposeError):
        build_embedding_model(load_settings(), provider="anthropic")
