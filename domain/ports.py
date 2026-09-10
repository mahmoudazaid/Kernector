"""Ports: the interfaces infrastructure must satisfy."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    ConnectorDocument,
    DocumentChunk,
    EmbeddedChunk,
    ScoredChunk,
    SourceDocument,
    SourceReference,
    SourceType,
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

    def list_source_chunks(
        self,
        reference: SourceReference,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[DocumentChunk]:
        """Return chunks for one complete source reference.

        Scoped by the whole `SourceReference`, so the same `source_id` under a
        different `source_type` is excluded. A reference matching no stored
        record returns an empty sequence. Results are ordered by ascending
        ``chunk.index``. Optional ``limit``/``offset`` page **positionally**
        after that order (not by raw ``chunk.index`` values, which may have
        gaps). ``offset`` must be ``>= 0``. A non-positive ``limit`` yields an
        empty sequence. Does not return or compute embeddings.

        Raises:
            VectorStoreError: On any adapter-level failure, including a negative
                ``offset`` or a non-int ``limit``/``offset`` where the adapter
                validates types.
        """


class LexicalIndex(Protocol):
    """A lexical (e.g. BM25) index of chunk text searchable by query string."""

    def upsert(self, embedded: Sequence[EmbeddedChunk]) -> None:
        """Insert or replace chunks keyed by their derived identity.

        Idempotent: re-adding the same identity replaces content and metadata.
        Empty ``embedded`` is a no-op.
        """

    def search(
        self,
        query: str,
        limit: int,
        *,
        metadata_filters: Mapping[str, str] | None = None,
    ) -> Sequence[ScoredChunk]:
        """Return the ``limit`` best lexical matches for ``query``, best first.

        Filters apply **before** the limit with the same ``extra`` AND semantics
        as ``VectorStore.search``. ``None`` and ``{}`` mean unfiltered.
        Empty corpus or ``limit <= 0`` returns an empty sequence.
        """

    def delete_source(self, reference: SourceReference) -> None:
        """Remove all chunks for ``reference``. Missing references are a no-op."""


class Tool(Protocol):
    """A named capability a use case can expose to the model."""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    def run(self, arguments: Mapping[str, object]) -> str:
        """Execute the tool with ``arguments`` and return a string result.

        Raises:
            ToolArgumentValidationError: Arguments were rejected before work.
            ToolFailureError: The tool invocation failed after valid arguments.
        """
        ...


class DocumentCatalog(Protocol):
    """Durable metadata registry for catalogued knowledge documents."""

    def all(self) -> Sequence[CatalogDocument]:
        """Return every catalog record, reloading durable state if needed."""

    def get(self, reference: SourceReference) -> CatalogDocument | None:
        """Return the record for ``reference``, or ``None`` when absent."""

    def upsert(self, document: CatalogDocument) -> None:
        """Insert or replace the record keyed by ``document.reference``."""

    def delete(self, reference: SourceReference) -> None:
        """Remove the record for ``reference``. Missing references are a no-op."""

    def count(
        self,
        *,
        source_type: SourceType | None = None,
        status: CatalogStatus | None = None,
    ) -> int:
        """Return how many records match the optional filters.

        Args:
            source_type (SourceType | None): Limit to this source, or all sources.
            status (CatalogStatus | None): Limit to this status, or all statuses.

        Returns:
            int: Matching catalog row count.
        """
        ...


class DocumentExtractor(Protocol):
    """Turns an upload payload into a normalized source document."""

    def extract(
        self,
        payload: UploadPayload,
        *,
        reference: SourceReference,
    ) -> SourceDocument:
        """Extract text and metadata for ``payload`` under ``reference``."""


class KnowledgeConnector(Protocol):
    """Lists and fetches remote knowledge files as domain documents."""

    def list_documents(self) -> Sequence[ConnectorDocument]:
        """Return the currently visible remote documents.

        Raises:
            ConnectorError: Listing failed without exposing provider details.
            ConnectorAuthError: Credentials or permissions were rejected.
            ConnectorUnavailableError: The provider is unreachable or throttling.
        """
        ...

    def fetch_document(
        self,
        document: ConnectorDocument,
    ) -> SourceDocument:
        """Download or export ``document`` as a normalized source.

        Raises:
            ConnectorError: The file could not be read without exposing provider details.
            ConnectorAuthError: Credentials or permissions were rejected.
            ConnectorUnavailableError: The provider is unreachable or throttling.
        """
        ...
