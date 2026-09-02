"""Tests for RecordingChatModel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from composition.recording_chat import RecordingChatModel
from domain.models import AskResult, Message, Usage


class _Inner:
    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        return AskResult(
            content="ok",
            model="m",
            latency_ms=7,
            usage=Usage(total_tokens=3),
            settings=dict(settings),
        )


def test_recording_chat_model_keeps_and_consumes_last_result() -> None:
    recording = RecordingChatModel(_Inner())  # type: ignore[arg-type]
    first = recording.complete("sys", (Message(role="user", content="a"),), {"t": 0})
    assert first.latency_ms == 7
    assert recording.consume_last() is first
    assert recording.consume_last() is None
