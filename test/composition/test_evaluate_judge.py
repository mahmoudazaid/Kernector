"""Live eval composition refuses DeterministicChatModel as the answer model."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from application.errors import ApplicationValidationError, ConfigurationError, ObservationIntegrityError
from composition.evaluate import (
    JudgeSkipped,
    LiveObservedRagSession,
    load_rag_judge_baseline,
    reject_deterministic_answer_model,
    run_rag_judge,
)
from domain.errors import ProviderError
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


def test_load_baseline_rejects_non_utf8(tmp_path: Path) -> None:
    path = tmp_path / "rag-judge-baseline.json"
    path.write_bytes(b"\xff\xfe{not-utf8")
    with pytest.raises(ApplicationValidationError, match="UTF-8"):
        load_rag_judge_baseline(path)


def test_one_failed_observation_does_not_abort_remaining(
    env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from application.rag_judge_contracts import AnswerRunMetadata
    from test.fixtures.rag_judge import (
        coverage_cases,
        observations_for,
        scripted_judge,
    )

    cases = coverage_cases()
    observations = observations_for(cases)
    seen: list[str] = []

    class _Runner:
        def execute(self, case):
            seen.append(case.id)
            if case.id == "cross":
                raise ProviderError("sk-secret-token")
            return observations[case.id]

    session = LiveObservedRagSession(
        runner=_Runner(),
        answer_meta=AnswerRunMetadata(provider="openrouter", model="answer-model"),
        persist_path=tmp_path,
        rewriter="openrouter-rewrite",
        embedding_model="embed-model",
    )

    @contextmanager
    def _fake_session(*args, **kwargs):
        del args, kwargs
        yield session

    env.setattr("composition.evaluate.live_observed_rag_session", _fake_session)
    report = run_rag_judge(
        "live",
        cases,
        settings=load_settings(),
        judge=scripted_judge('{"score": 1.0, "explanation": "ok"}'),
        baseline_path=tmp_path / "missing-baseline.json",
    )
    assert seen == [case.id for case in cases]
    cross = next(item for item in report.results if item.case_id == "cross")
    assert cross.error_type == "judge_error"
    scored = next(item for item in report.results if item.case_id == "irr")
    assert scored.metrics["faithfulness"].status == "scored"
    assert "sk-secret-token" not in str(report)


def test_observation_integrity_is_logged_without_error_text(
    env: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import json
    import logging

    from application.rag_judge_contracts import AnswerRunMetadata
    from test.fixtures.rag_judge import coverage_cases, observations_for, scripted_judge

    cases = coverage_cases()
    observations = observations_for(cases)

    class _Runner:
        def execute(self, case):
            if case.id == "cross":
                raise ObservationIntegrityError("generation_hits missing for case cross")
            return observations[case.id]

    session = LiveObservedRagSession(
        runner=_Runner(),
        answer_meta=AnswerRunMetadata(provider="openrouter", model="answer-model"),
        persist_path=tmp_path,
        rewriter="openrouter-rewrite",
        embedding_model="embed-model",
    )

    @contextmanager
    def _fake_session(*args, **kwargs):
        del args, kwargs
        yield session

    env.setattr("composition.evaluate.live_observed_rag_session", _fake_session)
    with caplog.at_level(logging.INFO, logger="composition.evaluate"):
        report = run_rag_judge(
            "live",
            cases,
            settings=load_settings(),
            judge=scripted_judge('{"score": 1.0, "explanation": "ok"}'),
            baseline_path=tmp_path / "missing-baseline.json",
        )
    cross = next(item for item in report.results if item.case_id == "cross")
    assert cross.error_type == "observation_integrity"
    records = [json.loads(record.message) for record in caplog.records]
    observe = next(item for item in records if item.get("operation") == "judge_observe")
    assert observe["error_type"] == "observation_integrity"
    assert observe["case_id"] == "cross"
    assert "generation_hits missing" not in caplog.text


def test_input_rejected_is_judge_error_not_integrity(
    env: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import json
    import logging

    from application.errors import InputRejectedError
    from application.rag_judge_contracts import AnswerRunMetadata
    from test.fixtures.rag_judge import coverage_cases, observations_for, scripted_judge

    cases = coverage_cases()
    observations = observations_for(cases)

    class _Runner:
        def execute(self, case):
            if case.id == "cite":
                raise InputRejectedError("query rejected")
            return observations[case.id]

    session = LiveObservedRagSession(
        runner=_Runner(),
        answer_meta=AnswerRunMetadata(provider="openrouter", model="answer-model"),
        persist_path=tmp_path,
        rewriter="openrouter-rewrite",
        embedding_model="embed-model",
    )

    @contextmanager
    def _fake_session(*args, **kwargs):
        del args, kwargs
        yield session

    env.setattr("composition.evaluate.live_observed_rag_session", _fake_session)
    with caplog.at_level(logging.INFO, logger="composition.evaluate"):
        report = run_rag_judge(
            "live",
            cases,
            settings=load_settings(),
            judge=scripted_judge('{"score": 1.0, "explanation": "ok"}'),
            baseline_path=tmp_path / "missing-baseline.json",
        )
    cite = next(item for item in report.results if item.case_id == "cite")
    assert cite.error_type == "judge_error"
    records = [json.loads(record.message) for record in caplog.records]
    observe = next(
        item
        for item in records
        if item.get("operation") == "judge_observe" and item.get("case_id") == "cite"
    )
    assert observe["error_type"] == "judge_error"
    assert observe["exception_type"] == "InputRejectedError"
