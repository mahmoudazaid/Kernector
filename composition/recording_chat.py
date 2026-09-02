"""ChatModel wrapper that records safe RunMeta for tool-turn observability."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from application.contracts import RunMeta
from domain.models import AskResult, Message
from domain.ports import ChatModel


class RecordingChatModel:
    """Delegate to an inner ``ChatModel`` and keep a safe metadata snapshot.

    Used so tool chains that call the model through the opaque invoke boundary
    can still surface latency / tokens on ``ToolRunOutcome.run`` without retaining
    model response bodies or putting metadata into tool JSON payloads.

    At most one model call may be recorded between ``clear`` / ``consume``
    cycles: Software Delivery tool runs invoke the chat model once
    (test-case generation). A second call fails clearly rather than silently
    dropping earlier latency or token usage.
    """

    def __init__(self, inner: ChatModel) -> None:
        self._inner = inner
        self._last: RunMeta | None = None

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        if self._last is not None:
            raise RuntimeError(
                "RecordingChatModel already recorded a model call for this run"
            )
        result = self._inner.complete(system, messages, settings)
        self._last = RunMeta.from_result(result)
        return result

    def clear(self) -> None:
        """Discard any recorded metadata without returning it."""
        self._last = None

    def consume(self) -> RunMeta | None:
        """Return and clear the recorded safe metadata (if any)."""
        last, self._last = self._last, None
        return last
