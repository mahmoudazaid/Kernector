"""Process-scoped clarification context for multi-turn workflow follow-ups.

Ask stacks are rebuilt per HTTP request, so this store must live outside
``ToolAugmentedAsk`` instances. Keys are trusted ``conversation_id`` values
only — no secrets or raw tool payloads.
"""

from __future__ import annotations

from collections.abc import Mapping
from threading import Lock
from typing import Protocol


class ClarificationContextStore(Protocol):
    """Get/set structured prior clarification context by conversation id."""

    def get(self, conversation_id: str | None) -> Mapping[str, object] | None:
        """Return prior context for ``conversation_id``, or None."""

    def set(
        self,
        conversation_id: str | None,
        context: Mapping[str, object] | None,
    ) -> None:
        """Store or clear context for ``conversation_id`` (no-op if id missing)."""


class InMemoryClarificationContextStore:
    """Thread-safe in-process map of conversation_id → clarification context."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._by_conversation: dict[str, dict[str, object]] = {}

    def get(self, conversation_id: str | None) -> Mapping[str, object] | None:
        if not conversation_id or not conversation_id.strip():
            return None
        with self._lock:
            stored = self._by_conversation.get(conversation_id)
            return None if stored is None else dict(stored)

    def set(
        self,
        conversation_id: str | None,
        context: Mapping[str, object] | None,
    ) -> None:
        if not conversation_id or not conversation_id.strip():
            return
        with self._lock:
            if context is None:
                self._by_conversation.pop(conversation_id, None)
                return
            self._by_conversation[conversation_id] = dict(context)


__all__ = [
    "ClarificationContextStore",
    "InMemoryClarificationContextStore",
]
