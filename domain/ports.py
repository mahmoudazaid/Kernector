"""Ports: the interfaces infrastructure must satisfy."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from domain.artifacts import Artifact, ArtifactReceipt
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    ChunkPage,
    ConnectorDocument,
    EmbeddedChunk,
    ScoredChunk,
    SourceDocument,
    SourceLocator,
    SourceReference,
    SourceType,
    UploadPayload,
    Vector,
)
from domain.models import AgentTurnResult, AskResult, Message, PromptVariant
from domain.response_feedback import ResponseFeedback, RunProvenance


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

    Invocation failures raise ``ProviderError`` (including actionable
    subclasses). Unusable model content raises ``QueryRewriterError`` so the
    application can wrap blank/non-string rewrites without collapsing
    auth/rate-limit categories into a generic rewrite failure.
    """

    def rewrite(self, query: str) -> str:
        """Return a non-blank retrieval-oriented query for ``query``.

        Raises:
            ProviderError: Invocation failed (including actionable subclasses).
            QueryRewriterError: Content was blank or not a string.
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
    ) -> ChunkPage:
        """Return a page of chunks for one complete source reference.

        Scoped by the whole `SourceReference`, so the same `source_id` under a
        different `source_type` is excluded. A reference matching no stored
        record returns an empty page. Results are ordered by ascending
        ``chunk.index``. Optional ``limit``/``offset`` page **positionally**
        after that order (not by raw ``chunk.index`` values, which may have
        gaps). ``offset`` must be ``>= 0``. A non-positive ``limit`` yields an
        empty page. ``has_more`` is based on the ordered id set **before**
        hydrate drops, so a skipped corrupt or vanished row cannot collapse
        pagination. Does not return or compute embeddings.

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
    """A named capability a use case can expose to the model.

    Optional attribute ``args_schema`` (``type | None``): when set to a
    Pydantic model type, tool-calling adapters bind it as the LLM argument
    schema. When absent or ``None``, adapters assume empty args. Declared on
    the port so the contract is checkable rather than a silent ``getattr``
    convention between application tools and infrastructure.
    """

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    args_schema: type | None

    def run(self, arguments: Mapping[str, object]) -> str:
        """Execute the tool with ``arguments`` and return a string result.

        Raises:
            ToolArgumentValidationError: Arguments were rejected before work.
            ToolFailureError: The tool invocation failed after valid arguments.
        """
        ...


class ToolCallingAgent(Protocol):
    """Plans and invokes bound tools in a multi-step loop until a final answer."""

    def run(
        self,
        goal: str,
        tools: Sequence[Tool],
        *,
        max_steps: int,
        conversation_id: str | None = None,
        system_prompt: str | None = None,
    ) -> AgentTurnResult:
        """Run the agent for ``goal`` with ``tools``, stopping by ``max_steps``.

        Bound tools are plain ``Tool`` ports (name, description, invoke), not
        vendor SDK objects. Optional ``conversation_id`` selects short-term
        thread memory when the adapter is configured with a checkpointer;
        workspace binding stays in composition/infrastructure.

        Optional ``system_prompt`` overrides the adapter's base system text for
        this invocation only (e.g. allowlisted response-style composition).
        Omitting it keeps the adapter's configured base prompt.

        Raises:
            ProviderError: The model or agent runtime failed.
            ToolArgumentValidationError: A tool rejected its arguments.
            ToolFailureError: A tool failed after accepting arguments.
        """
        ...


class AgentThreadMemory(Protocol):
    """Clears short-term agent thread state for a client conversation id."""

    def clear(self, *, conversation_id: str) -> None:
        """Drop checkpoints for ``conversation_id`` (idempotent).

        Workspace scoping is bound by the adapter at construction time.
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


class UploadBlobStore(Protocol):
    """Durable storage for raw upload payloads."""

    def put(self, reference: SourceReference, payload: UploadPayload) -> None: ...

    def get(self, reference: SourceReference) -> UploadPayload | None: ...

    def delete(self, reference: SourceReference) -> None: ...


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


class LiveSourceReader(Protocol):
    """Fetches one live remote source by locator (no catalog / vector store)."""

    def fetch(self, locator: SourceLocator) -> SourceDocument:
        """Return the current document for ``locator``.

        Raises:
            ConnectorError: Fetch failed without exposing provider details.
            ConnectorAuthError: Credentials or permissions were rejected.
            ConnectorNotFoundError: The remote resource does not exist.
            ConnectorRateLimitError: The provider rate-limited the call.
            ConnectorTimeoutError: The provider request timed out.
            ConnectorNetworkError: Transport failed before a usable response.
            ConnectorUnavailableError: The provider is temporarily unreachable.
        """
        ...


class ArtifactUploader(Protocol):
    """Uploads a typed artifact into a caller-chosen parent container.

    Raises:
        ConnectorError: Upload failed without exposing provider details.
        ConnectorAuthError: Credentials or permissions were rejected.
        ConnectorUnavailableError: The provider is unreachable or throttling.
    """

    def upload(self, artifact: Artifact, *, parent_id: str) -> ArtifactReceipt:
        """Persist ``artifact`` under ``parent_id`` and return its receipt."""
        ...


class ResponseFeedbackRepository(Protocol):
    """Durable store for per-response thumbs ratings.

    ``workspace_id`` is bound by the adapter at construction. Identity is
    ``(workspace_id, request_id)``.
    """

    def upsert(self, feedback: ResponseFeedback) -> ResponseFeedback:
        """Insert or replace the rating for ``feedback.request_id``."""
        ...

    def get(self, request_id: str) -> ResponseFeedback | None:
        """Return the in-workspace rating for ``request_id``, or ``None``."""
        ...

    def delete(self, request_id: str) -> bool:
        """Remove the in-workspace rating. Return whether a row was deleted."""
        ...


class RunProvenanceLookup(Protocol):
    """Trusted request_id → run metadata (null until a run ledger exists)."""

    def get(self, request_id: str) -> RunProvenance | None:
        """Return server-side provenance for ``request_id``, or ``None``."""
        ...
