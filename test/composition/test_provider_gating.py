"""Composition purpose gating before factory/client invocation (#462)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from composition.container import (
    build_chat_model,
    build_embedding_model,
    build_rewrite_and_retrieve_knowledge,
)
from domain.errors import UnknownProviderError, UnsupportedProviderPurposeError
from infrastructure.config import load_settings


def test_build_embedding_model_defaults_to_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    settings = load_settings()
    model = build_embedding_model(settings)
    assert type(model).__name__ == "OpenRouterEmbeddings"


def test_build_embedding_model_refuses_anthropic_before_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude")
    settings = load_settings()
    with pytest.raises(UnsupportedProviderPurposeError, match="does not support"):
        build_embedding_model(settings, provider="anthropic")


def test_build_embedding_model_refuses_ollama_before_client() -> None:
    with pytest.raises(UnsupportedProviderPurposeError, match="does not support"):
        build_embedding_model(load_settings(), provider="ollama")


def test_build_embedding_model_unknown_provider() -> None:
    with pytest.raises(UnknownProviderError):
        build_embedding_model(load_settings(), provider="not-real")


def test_build_chat_model_unknown_provider_before_factory() -> None:
    with pytest.raises(UnknownProviderError):
        build_chat_model(load_settings(), provider="carrier-pigeon")


def test_build_openai_chat_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    settings = load_settings()
    model = build_chat_model(settings, provider="openai")
    assert type(model).__name__ == "OpenAIChat"


def test_build_anthropic_chat_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    settings = load_settings()
    model = build_chat_model(settings, provider="anthropic")
    assert type(model).__name__ == "AnthropicChat"


def test_build_gemini_chat_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
    settings = load_settings()
    model = build_chat_model(settings, provider="gemini")
    assert type(model).__name__ == "GeminiChat"


def test_build_openai_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    settings = load_settings()
    model = build_embedding_model(settings, provider="openai")
    assert type(model).__name__ == "OpenAIEmbeddings"


def test_build_gemini_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    settings = load_settings()
    model = build_embedding_model(settings, provider="gemini")
    assert type(model).__name__ == "GeminiEmbeddings"


def test_rewrite_builder_gates_unsupported_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings()
    # Force a known provider then replace provider with something that
    # cannot rewrite only if we had one — all chat providers support rewrite.
    # Unknown id still gates before network.
    broken = replace(settings, provider="not-a-provider")
    with pytest.raises(UnknownProviderError):
        build_rewrite_and_retrieve_knowledge(broken)
