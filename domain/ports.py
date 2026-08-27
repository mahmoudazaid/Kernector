"""Ports: the interfaces infrastructure must satisfy."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from domain.knowledge import EmbeddedChunk, ScoredChunk, SourceReference, Vector
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

    def upsert(self, embedded: Sequence[EmbeddedChunk]) -> None:
        """Update or Insert embedded chunks if it's not already in the store, 
        keyed by their derived identity.

        Idempotent: re-adding a chunk with the same derived identity replaces
        its content, vector, and metadata rather than creating a second record.
        Returns without effect when `embedded` is empty.

        Raises:
            RuntimeError: a subclass, on any adapter-level failure.
        """

    def search(self, vector: Vector, limit: int) -> Sequence[ScoredChunk]:
        """Return the `limit` nearest chunks to `vector`, nearest first.

        Returns an empty sequence when `limit <= 0` or the store is empty.
        A `limit` that is not an `int` is rejected; `bool` is rejected
        specifically rather than letting `False` fall through to the
        `limit <= 0` rule.

        Scores are cosine similarity in `[-1.0, 1.0]`, higher is nearer.
        Negative scores are legitimate and are never clamped.

        Raises:
            RuntimeError: a subclass, on any adapter-level failure.
        """

    def delete_source(self, reference: SourceReference) -> None:
        """Delete all chunks belonging to one complete source reference.

        Scoped by the whole `SourceReference`, so the same `source_id` under a
        different `source_type` is left untouched, as is every other source.
        A reference matching no stored record is a no-op, not an error.

        Enables replacement on re-ingestion: deleting a source and upserting
        its freshly generated chunks leaves no stale higher-index records
        behind when the new content chunks into fewer pieces.

        Raises:
            RuntimeError: a subclass, on any adapter-level failure.
        """


class Tool(Protocol):
    """A named capability a use case can expose to the model."""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    def run(self, arguments: Mapping[str, object]) -> str: ...
