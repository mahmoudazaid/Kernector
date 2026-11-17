"""Tests for RecordingChatModel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from application.contracts import RunMeta
from composition.chat.recording_chat import RecordingChatModel
from domain.models import AskResult, Message, Usage

SECRET_MARKER = "SECRET_MODEL_BODY_do_not_retain_xyz"


class _Inner:
    def __init__(self, content: str = "ok") -> None:
        self._content = content
        self.calls = 0

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        self.calls += 1
        return AskResult(
            content=self._content,
            model="m",
            latency_ms=7 * self.calls,
            usage=Usage(total_tokens=3 * self.calls),
            settings=dict(settings),
        )


def test_recording_chat_model_consumes_safe_run_meta_not_ask_result() -> None:
    recording = RecordingChatModel(_Inner())  # type: ignore[arg-type]
    first = recording.complete("sys", (Message(role="user", content="a"),), {"t": 0})
    assert first.latency_ms == 7
    meta = recording.consume()
    assert meta == RunMeta(
        model="m",
        latency_ms=7,
        usage=Usage(total_tokens=3),
        settings={"t": 0},
    )
    assert recording.consume() is None


def test_recorder_does_not_retain_raw_model_content() -> None:
    recording = RecordingChatModel(_Inner(SECRET_MARKER))  # type: ignore[arg-type]
    recording.complete("sys", (Message(role="user", content="a"),), {})
    meta = recording.consume()
    assert meta is not None
    assert SECRET_MARKER not in repr(meta)
    assert SECRET_MARKER not in str(meta)
    assert not hasattr(meta, "content")


def test_second_model_call_before_consume_fails_clearly() -> None:
    """Architecture records at most one ChatModel call per tool run."""
    recording = RecordingChatModel(_Inner())  # type: ignore[arg-type]
    recording.complete("sys", (Message(role="user", content="a"),), {})
    with pytest.raises(RuntimeError, match="already recorded"):
        recording.complete("sys", (Message(role="user", content="b"),), {})


def test_accumulate_merges_successive_model_calls() -> None:
    recording = RecordingChatModel(_Inner(), accumulate=True)  # type: ignore[arg-type]
    recording.complete("sys", (Message(role="user", content="a"),), {})
    recording.complete("sys", (Message(role="user", content="b"),), {})
    meta = recording.consume()
    assert meta is not None
    assert meta.latency_ms == 21  # 7 + 14
    assert meta.usage is not None
    assert meta.usage.total_tokens == 9  # 3 + 6


def test_record_observation_merges_when_accumulating() -> None:
    recording = RecordingChatModel(_Inner(), accumulate=True)  # type: ignore[arg-type]
    recording.record(RunMeta(model="agent", latency_ms=10, usage=Usage(total_tokens=2)))
    recording.record(RunMeta(model="agent", latency_ms=5, usage=Usage(total_tokens=4)))
    meta = recording.consume()
    assert meta == RunMeta(
        model="agent",
        latency_ms=15,
        usage=Usage(total_tokens=6),
        settings={},
    )


def test_accumulate_keeps_cost_unknown_when_any_call_cost_is_missing() -> None:
    """Known + unknown must not invent a partial dollar amount (#49 / PR #425 P2)."""
    recording = RecordingChatModel(_Inner(), accumulate=True)  # type: ignore[arg-type]
    recording.record(
        RunMeta(
            model="agent",
            usage=Usage(prompt_tokens=10, completion_tokens=4, total_tokens=14, cost=0.0012),
        )
    )
    recording.record(
        RunMeta(
            model="agent",
            usage=Usage(prompt_tokens=3, completion_tokens=2, total_tokens=5, cost=None),
        )
    )
    meta = recording.consume()
    assert meta is not None
    assert meta.usage == Usage(
        prompt_tokens=13,
        completion_tokens=6,
        total_tokens=19,
        cost=None,
    )


def test_accumulate_keeps_cost_unknown_when_zero_meets_unknown() -> None:
    recording = RecordingChatModel(_Inner(), accumulate=True)  # type: ignore[arg-type]
    recording.record(
        RunMeta(model="agent", usage=Usage(total_tokens=2, cost=0.0))
    )
    recording.record(
        RunMeta(model="agent", usage=Usage(total_tokens=3, cost=None))
    )
    meta = recording.consume()
    assert meta is not None
    assert meta.usage == Usage(total_tokens=5, cost=None)


def test_accumulate_treats_missing_usage_as_unknown_cost_known_then_missing() -> None:
    """usage=None on a later call must not leave a falsely complete cost total."""
    recording = RecordingChatModel(_Inner(), accumulate=True)  # type: ignore[arg-type]
    recording.record(
        RunMeta(model="agent", usage=Usage(total_tokens=4, cost=0.002))
    )
    recording.record(RunMeta(model="agent", latency_ms=3))
    meta = recording.consume()
    assert meta is not None
    assert meta.latency_ms == 3
    assert meta.usage == Usage(total_tokens=4, cost=None)


def test_accumulate_treats_missing_usage_as_unknown_cost_missing_then_known() -> None:
    recording = RecordingChatModel(_Inner(), accumulate=True)  # type: ignore[arg-type]
    recording.record(RunMeta(model="agent", latency_ms=2))
    recording.record(
        RunMeta(model="agent", usage=Usage(total_tokens=7, cost=0.004))
    )
    meta = recording.consume()
    assert meta is not None
    assert meta.latency_ms == 2
    assert meta.usage == Usage(total_tokens=7, cost=None)


def test_accumulate_treats_zero_cost_plus_missing_usage_as_unknown() -> None:
    recording = RecordingChatModel(_Inner(), accumulate=True)  # type: ignore[arg-type]
    recording.record(
        RunMeta(model="agent", usage=Usage(total_tokens=2, cost=0.0))
    )
    recording.record(RunMeta(model="agent", latency_ms=1))
    meta = recording.consume()
    assert meta is not None
    assert meta.usage == Usage(total_tokens=2, cost=None)


def test_accumulate_later_known_cost_cannot_restore_total_after_missing_usage() -> None:
    recording = RecordingChatModel(_Inner(), accumulate=True)  # type: ignore[arg-type]
    recording.record(
        RunMeta(model="agent", usage=Usage(total_tokens=4, cost=0.002))
    )
    recording.record(RunMeta(model="agent", latency_ms=3))
    recording.record(
        RunMeta(model="agent", usage=Usage(total_tokens=5, cost=0.01))
    )
    meta = recording.consume()
    assert meta is not None
    assert meta.usage == Usage(total_tokens=9, cost=None)


def test_accumulate_sums_fully_known_costs() -> None:
    recording = RecordingChatModel(_Inner(), accumulate=True)  # type: ignore[arg-type]
    recording.record(
        RunMeta(model="agent", usage=Usage(total_tokens=1, cost=0.001))
    )
    recording.record(
        RunMeta(model="agent", usage=Usage(total_tokens=2, cost=0.0025))
    )
    meta = recording.consume()
    assert meta is not None
    assert meta.usage == Usage(total_tokens=3, cost=0.0035)


def test_accumulate_treats_explicit_zero_costs_as_known() -> None:
    recording = RecordingChatModel(_Inner(), accumulate=True)  # type: ignore[arg-type]
    recording.record(
        RunMeta(model="agent", usage=Usage(total_tokens=1, cost=0.0))
    )
    recording.record(
        RunMeta(model="agent", usage=Usage(total_tokens=2, cost=0.0))
    )
    meta = recording.consume()
    assert meta is not None
    assert meta.usage == Usage(total_tokens=3, cost=0.0)


def test_accumulate_unknown_cost_projects_null_cost_for_ui_fallback() -> None:
    """Merged unknown cost stays null on the HTTP allowlist (UI shows Cost: N/A)."""
    from presentation.http.schemas import run_meta_response

    recording = RecordingChatModel(_Inner(), accumulate=True)  # type: ignore[arg-type]
    recording.record(
        RunMeta(
            model="agent",
            provider="openrouter",
            usage=Usage(total_tokens=10, cost=0.01),
        )
    )
    recording.record(
        RunMeta(
            model="agent",
            provider="openrouter",
            usage=Usage(total_tokens=5, cost=None),
        )
    )
    meta = recording.consume()
    assert meta is not None
    projected = run_meta_response(meta)
    assert projected is not None
    assert projected.cost is None
    assert projected.total_tokens == 15
    assert projected.provider == "openrouter"


def test_accumulate_missing_usage_projects_null_cost_for_ui_fallback() -> None:
    from presentation.http.schemas import run_meta_response

    recording = RecordingChatModel(_Inner(), accumulate=True)  # type: ignore[arg-type]
    recording.record(
        RunMeta(
            model="agent",
            provider="openrouter",
            usage=Usage(total_tokens=4, cost=0.002),
        )
    )
    recording.record(RunMeta(model="agent", provider="openrouter", latency_ms=3))
    meta = recording.consume()
    assert meta is not None
    projected = run_meta_response(meta)
    assert projected is not None
    assert projected.cost is None
    assert projected.total_tokens == 4
    assert projected.provider == "openrouter"


def test_clear_discards_recording_without_returning_it() -> None:
    recording = RecordingChatModel(_Inner())  # type: ignore[arg-type]
    recording.complete("sys", (Message(role="user", content="a"),), {})
    recording.clear()
    assert recording.consume() is None
