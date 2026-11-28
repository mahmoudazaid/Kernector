"""Env bootstrap settings for OpenAI / Anthropic / Gemini (#462)."""

from __future__ import annotations

import pytest

from infrastructure.config import load_settings


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_EMBEDDING_MODEL",
        "OPENAI_TIMEOUT",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_TIMEOUT",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GEMINI_EMBEDDING_MODEL",
        "GEMINI_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_openai_settings_defaults(env: pytest.MonkeyPatch) -> None:
    openai = load_settings().openai
    assert openai.api_key is None
    assert openai.model is None
    assert openai.embedding_model == "text-embedding-3-small"
    assert openai.timeout == 120.0


def test_openai_settings_load_from_env(env: pytest.MonkeyPatch) -> None:
    env.setenv("OPENAI_API_KEY", "sk-openai")
    env.setenv("OPENAI_MODEL", "gpt-4o-mini")
    env.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
    env.setenv("OPENAI_TIMEOUT", "30")
    openai = load_settings().openai
    assert openai.api_key == "sk-openai"
    assert openai.model == "gpt-4o-mini"
    assert openai.embedding_model == "text-embedding-3-large"
    assert openai.timeout == 30.0


def test_anthropic_settings_defaults(env: pytest.MonkeyPatch) -> None:
    anthropic = load_settings().anthropic
    assert anthropic.api_key is None
    assert anthropic.model is None
    assert anthropic.timeout == 120.0


def test_anthropic_settings_load_from_env(env: pytest.MonkeyPatch) -> None:
    env.setenv("ANTHROPIC_API_KEY", "sk-ant")
    env.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    env.setenv("ANTHROPIC_TIMEOUT", "45")
    anthropic = load_settings().anthropic
    assert anthropic.api_key == "sk-ant"
    assert anthropic.model == "claude-sonnet-4-5"
    assert anthropic.timeout == 45.0


def test_gemini_settings_defaults(env: pytest.MonkeyPatch) -> None:
    gemini = load_settings().gemini
    assert gemini.api_key is None
    assert gemini.model is None
    assert gemini.embedding_model == "models/text-embedding-004"
    assert gemini.timeout == 120.0


def test_gemini_settings_load_from_env(env: pytest.MonkeyPatch) -> None:
    env.setenv("GEMINI_API_KEY", "gem-key")
    env.setenv("GEMINI_MODEL", "gemini-2.0-flash")
    env.setenv("GEMINI_EMBEDDING_MODEL", "models/embedding-001")
    env.setenv("GEMINI_TIMEOUT", "60")
    gemini = load_settings().gemini
    assert gemini.api_key == "gem-key"
    assert gemini.model == "gemini-2.0-flash"
    assert gemini.embedding_model == "models/embedding-001"
    assert gemini.timeout == 60.0
