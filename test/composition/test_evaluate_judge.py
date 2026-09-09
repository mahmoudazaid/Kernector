"""Live eval composition refuses DeterministicChatModel as the answer model."""

from __future__ import annotations

import pytest

from application.errors import ConfigurationError
from composition.evaluate import (
    JudgeSkipped,
    reject_deterministic_answer_model,
    run_rag_judge,
)
from infrastructure.config import load_settings
from infrastructure.eval.deterministic_chat import DeterministicChatModel


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("RAG_JUDGE_PROVIDER", raising=False)
    monkeypatch.delenv("RAG_JUDGE_MODEL", raising=False)
    monkeypatch.delenv("HTTP_CORS_ORIGINS", raising=False)
    return monkeypatch


def test_reject_deterministic_answer_model() -> None:
    with pytest.raises(ConfigurationError, match="DeterministicChatModel"):
        reject_deterministic_answer_model(DeterministicChatModel())


def test_auto_never_fakes(env: pytest.MonkeyPatch) -> None:
    settings = load_settings()
    with pytest.raises(JudgeSkipped, match="refusing to substitute fake scores"):
        run_rag_judge("auto", (), settings=settings)
