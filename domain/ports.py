"""Ports: the interfaces infrastructure must satisfy."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from domain.models import AskResult, Message, PromptVariant

class ChatModel(Protocol):
    """A provider that can answer a conversation."""

    def complete(
        self, 
        system: str, 
        messages: Sequence[Message], 
        settings: Mapping[str, object]
        ) -> AskResult: ...

class PromptRepository(Protocol):
    """A source of prompt variants."""

    def all(self) -> Mapping[str, PromptVariant]: ...

    def default_key(self) -> str: ...