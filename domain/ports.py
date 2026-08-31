"""Ports: the interfaces infrastructure must satisfy."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from domain.knowledge import (
    CatalogDocument,
    EmbeddedChunk,
    ScoredChunk,
    SourceDocument,
    SourceReference,
    UploadPayload,
    Vector,
)
from domain.models import AskResult, Message, PromptVariant


class ChatModel(Protocol):
    """A provider that can answer a conversation."""

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        """Return a model completion for ``system`` plus ``messages``.

        Raises:
            ProviderError: The provider call failed at runtime.
        """
        ...


class PromptRepository(Protocol):
    """A source of prompt variants."""

    def all(self) -> Mapping[str, PromptVariant]: ...

    def default_key(self) -> str | None: ...


class EmbeddingModel(Protocol):
    """A provider that turns text into vectors."""

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Vector]:
        """Embed each text; return one vector per input, same order.

        Raises:
            ProviderError: The embedding provider call failed at runtime.
        """
        ...

    def embed_query(self, text: str) -> Vector:
        """Embed a single query string.

        Raises:
            ProviderError: The embedding provider call failed at runtime.
        """
        ...


class QueryRewriter(Protocol):
    """Rewrites a natural-language query into a retrieval-oriented string.

    Names ``QueryRewriterError`` (a ``ProviderError``) so the application can
    catch one known type rather than every ``RuntimeError``.
    """

    def rewrite(self, query: str) -> str:
        """Return a non-blank retrieval-oriented query for ``query``.

        Raises:
            QueryRewriterError: Invocation failed or content was unusable.
        """
        ...


class VectorStore(Protocol):
    """A store of embedded chunks that can be searched by similarity."""

    def upsert(self, embedded: Sequence[EmbeddedChunk]) -> None:
        """Update or Insert embedded chunks if it's not already in the store,
        keyed by their derived identity.

        Idempotent: re-adding a chunk with the same derived identity replaces
        its content, vector, and metadata rather than creating a second record.
        Returns without effect when `embedded` is empty.

        Raises:
            VectorStoreError: On any adapter-level failure.
        """

    def search(
        self,
        vector: Vector,
        limit: int,
        *,
        metadata_filters: Mapping[str, str] | None = None,
    ) -> Sequence[ScoredChunk]:
        """Return the `limit` nearest chunks to `vector`, nearest first.

        Filters are applied **before** the limit: `limit` is the count of
        nearest chunks among those that match, not a post-filter slice of an
        unfiltered top-k. `None` and `{}` both mean unfiltered top-k.

        When `metadata_filters` is non-empty, every supplied key/value pair must
        exact-match a key in `SourceMetadata.extra` (AND semantics). A missing
        key is a non-match. Owned scalar provenance fields (`title`,
        `source_id`, …) are not filter targets.

        Returns an empty sequence when `limit <= 0` or the store is empty.
        A `limit` that is not an `int` is rejected; `bool` is rejected
        specifically rather than letting `False` fall through to the
        `limit <= 0` rule.

        Adapters reject a non-mapping `metadata_filters` and non-string keys or
        values. An empty-string filter value is legal and matches an empty
        stored value.

        Scores are cosine similarity in `[-1.0, 1.0]`, higher is nearer.
        Negative scores are legitimate and are never clamped.

        Raises:
            VectorStoreError: On any adapter-level failure.
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
            VectorStoreError: On any adapter-level failure.
        """


class Tool(Protocol):
    """A named capability a use case can expose to the model."""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    def run(self, arguments: Mapping[str, object]) -> str:
        """Execute the tool with ``arguments`` and return a string result.

        Raises:
            ToolFailureError: The tool invocation failed.
        """
        ...


class DocumentCatalog(Protocol):
    """Durable metadata registry for uploaded knowledge documents."""

    def all(self) -> Sequence[CatalogDocument]:
        """Return every catalog record, reloading durable state if needed."""

    def get(self, reference: SourceReference) -> CatalogDocument | None:
        """Return the record for ``reference``, or ``None`` when absent."""

    def upsert(self, document: CatalogDocument) -> None:
        """Insert or replace the record keyed by ``document.reference``."""

    def delete(self, reference: SourceReference) -> None:
        """Remove the record for ``reference``. Missing references are a no-op."""


class DocumentExtractor(Protocol):
    """Turns an upload payload into a normalized source document."""

    def extract(
        self,
        payload: UploadPayload,
        *,
        reference: SourceReference,
    ) -> SourceDocument:
        """Extract text and metadata for ``payload`` under ``reference``."""
