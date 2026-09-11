"""Independent RAG_JUDGE_* settings never default from LLM_PROVIDER."""

from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.config import (
    judge_complete_kwargs,
    judge_config_ready,
    live_answer_config_ready,
    load_settings,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_REWRITE_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("RAG_JUDGE_PROVIDER", raising=False)
    monkeypatch.delenv("RAG_JUDGE_MODEL", raising=False)
    monkeypatch.delenv("RAG_JUDGE_BASE_URL", raising=False)
    monkeypatch.delenv("RAG_JUDGE_SEED", raising=False)
    monkeypatch.delenv("HTTP_CORS_ORIGINS", raising=False)
    return monkeypatch


def test_judge_settings_are_independent_of_llm_provider(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("LLM_PROVIDER", "openrouter")
    env.setenv("OPENROUTER_API_KEY", "sk-answer")
    env.setenv("OPENROUTER_MODEL", "answer-model")
    settings = load_settings()
    assert settings.provider == "openrouter"
    assert settings.rag_judge.provider is None
    assert settings.rag_judge.model is None
    assert judge_config_ready(settings) is False


def test_ollama_judge_ready_without_openrouter_key(env: pytest.MonkeyPatch) -> None:
    env.setenv("LLM_PROVIDER", "openrouter")
    env.setenv("RAG_JUDGE_PROVIDER", "ollama")
    env.setenv("RAG_JUDGE_MODEL", "llama3")
    env.setenv("RAG_JUDGE_BASE_URL", "http://127.0.0.1:11434")
    settings = load_settings()
    assert judge_config_ready(settings) is True
    assert settings.openrouter.api_key is None


def test_openrouter_judge_requires_key_and_model(env: pytest.MonkeyPatch) -> None:
    env.setenv("RAG_JUDGE_PROVIDER", "openrouter")
    env.setenv("RAG_JUDGE_MODEL", "judge-model")
    env.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    assert judge_config_ready(load_settings()) is False
    env.setenv("OPENROUTER_API_KEY", "sk-judge")
    assert judge_config_ready(load_settings()) is True


def test_invalid_judge_provider_is_rejected(env: pytest.MonkeyPatch) -> None:
    env.setenv("RAG_JUDGE_PROVIDER", "openai")
    with pytest.raises(ValueError, match="RAG_JUDGE_PROVIDER"):
        load_settings()


def test_seed_applied_only_for_openrouter(env: pytest.MonkeyPatch) -> None:
    env.setenv("RAG_JUDGE_PROVIDER", "openrouter")
    env.setenv("RAG_JUDGE_MODEL", "judge-model")
    env.setenv("RAG_JUDGE_SEED", "7")
    env.setenv("OPENROUTER_API_KEY", "sk")
    env.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    settings = load_settings()
    kwargs, applied = judge_complete_kwargs(settings)
    assert kwargs == {"temperature": 0, "seed": 7}
    assert applied == 7

    env.setenv("RAG_JUDGE_PROVIDER", "ollama")
    env.setenv("RAG_JUDGE_BASE_URL", "http://127.0.0.1:11434")
    settings = load_settings()
    kwargs, applied = judge_complete_kwargs(settings)
    assert kwargs == {"temperature": 0}
    assert applied is None


def test_live_answer_ready_is_provider_aware(env: pytest.MonkeyPatch) -> None:
    env.setenv("LLM_PROVIDER", "openrouter")
    env.setenv("OPENROUTER_API_KEY", "sk")
    env.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    env.setenv("OPENROUTER_MODEL", "answer-model")
    assert live_answer_config_ready(load_settings()) is True
    env.delenv("OPENROUTER_MODEL")
    assert live_answer_config_ready(load_settings()) is False


def test_chroma_default_is_unchanged(env: pytest.MonkeyPatch) -> None:
    assert load_settings().chroma.persist_path == PROJECT_ROOT / "data" / "chroma"
