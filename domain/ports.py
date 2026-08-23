"""Ports: the interfaces infrastructure must satisfy."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from domain.knowledge import EmbeddedChunk, ScoredChunk, Vector
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

class EmbeddingModel(Protocol):
    """A provider that turns text into vectors."""

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Vector]: ...

    def embed_query(self, text: str) -> Vector: ...


class VectorStore(Protocol):
    """A store of embedded chunks that can be searched by similarity."""

    def add(self, embedded: Sequence[EmbeddedChunk]) -> None: ...

    def search(self, vector: Vector, limit: int) -> Sequence[ScoredChunk]: ...


class Tool(Protocol):
    """A named capability a use case can expose to the model."""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    def run(self, arguments: Mapping[str, object]) -> str: ...
