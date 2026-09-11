"""Tests for RecordingChatModel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from application.contracts import RunMeta
from composition.recording_chat import RecordingChatModel
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


def test_clear_discards_recording_without_returning_it() -> None:
    recording = RecordingChatModel(_Inner())  # type: ignore[arg-type]
    recording.complete("sys", (Message(role="user", content="a"),), {})
    recording.clear()
    assert recording.consume() is None
