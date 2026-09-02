"""ChatModel wrapper that retains the last AskResult for RunMeta projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from domain.models import AskResult, Message
from domain.ports import ChatModel


class RecordingChatModel:
    """Delegate to an inner ``ChatModel`` and keep the latest ``AskResult``.

    Used so tool chains that call the model through the opaque invoke boundary
    can still surface latency / tokens on ``ToolRunOutcome.run`` without putting
    model metadata into tool JSON payloads.
    """

    def __init__(self, inner: ChatModel) -> None:
        self._inner = inner
        self._last: AskResult | None = None

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        result = self._inner.complete(system, messages, settings)
        self._last = result
        return result

    def consume_last(self) -> AskResult | None:
        """Return and clear the last recorded result (if any)."""
        last, self._last = self._last, None
        return last
