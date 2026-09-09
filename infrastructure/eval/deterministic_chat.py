"""Deterministic ChatModel for the offline eval harness."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from domain.models import AskResult, Message, Usage

OFFLINE_EVAL_ANSWER = "Grounded offline eval answer."


class DeterministicChatModel:
    """Returns a fixed non-insufficient answer with no network I/O.

    Args:
        answer (str): Completion text. Defaults to ``OFFLINE_EVAL_ANSWER``.
    """

    def __init__(self, answer: str = OFFLINE_EVAL_ANSWER) -> None:
        self._answer = answer

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        """Return the configured answer without calling a provider.

        Args:
            system (str): Unused system prompt.
            messages (Sequence[Message]): Unused conversation.
            settings (Mapping[str, object]): Copied onto the result.

        Returns:
            AskResult: Fixed content and empty usage.
        """
        del system, messages
        return AskResult(
            content=self._answer,
            model="eval-offline",
            latency_ms=0,
            usage=Usage(),
            settings=dict(settings),
        )
