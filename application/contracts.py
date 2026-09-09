"""Typed request/response contracts for core use cases.

UI-agnostic DTOs shared by HTTP and other presentation clients. Domain entities
are reused; prompt bodies and analysis-specific outputs stay out of scope.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from application.errors import ApplicationValidationError
from domain.knowledge import ScoredChunk, SourceDocument, SourceReference
from domain.models import AskResult, Message, Usage


def _require_text(value: object, field_name: str) -> str:
    """Reject anything that is not a non-blank string.

    The type check runs before the blankness check so a wrong type is reported
    as a wrong type. Fusing the two would report every rejection as "must be
    non-empty", which is false for an ``int`` and hides what actually arrived.

    Args:
        value (object): Candidate field value.
        field_name (str): Name used in the error message.

    Returns:
        str: The validated string.

    Raises:
        ApplicationValidationError: If ``value`` is blank or not a string.
    """
    if not isinstance(value, str):
        raise ApplicationValidationError(
            f"{field_name} must be a non-empty string, got {type(value).__name__}"
        )
    if not value.strip():
        raise ApplicationValidationError(f"{field_name} must be non-empty")
    return value


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    """Reject non-sequence collections (and strings/bytes).

    Args:
        value (object): Candidate collection.
        field_name (str): Name used in the error message.

    Returns:
        Sequence[object]: The validated sequence.

    Raises:
        ApplicationValidationError: If ``value`` is not a proper sequence.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ApplicationValidationError(
            f"{field_name} must be a sequence, got {type(value).__name__}"
        )
    return value


def _require_chunk_index(value: object) -> None:
    """Reject invalid optional citation chunk indexes.

    Args:
        value (object): Candidate ``chunk_index`` (``None`` is allowed).

    Raises:
        ApplicationValidationError: If set and not a non-negative ``int``.
    """
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApplicationValidationError(
            f"chunk_index must be a non-negative integer, "
            f"got {type(value).__name__}"
        )
    if value < 0:
        raise ApplicationValidationError(
            f"chunk_index must be a non-negative integer, got {value}"
        )


def _require_retrieval_limit(value: object) -> None:
    """Reject invalid optional retrieval limits.

    Args:
        value (object): Candidate ``retrieval_limit`` (``None`` is allowed).

    Raises:
        ApplicationValidationError: If set and not a positive ``int``.
    """
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApplicationValidationError(
            f"retrieval_limit must be a positive integer, "
            f"got {type(value).__name__}"
        )
    if value <= 0:
        raise ApplicationValidationError(
            f"retrieval_limit must be a positive integer, got {value}"
        )


def _require_positive_retrieval_limit(value: object) -> int:
    """Reject missing or invalid required retrieval limits.

    Args:
        value (object): Candidate ``retrieval_limit``.

    Returns:
        int: The validated positive limit.

    Raises:
        ApplicationValidationError: If not a positive ``int``.
    """
    _require_retrieval_limit(value)
    if value is None:
        raise ApplicationValidationError(
            f"retrieval_limit must be a positive integer, "
            f"got {type(value).__name__}"
        )
    return value


def _require_metadata_filters(
    value: object,
) -> dict[str, str] | None:
    """Validate and copy an optional opaque metadata filter map.

    Args:
        value (object): Candidate ``metadata_filters`` (``None`` is allowed).

    Returns:
        dict[str, str] | None: A plain copy, or ``None`` when absent.

    Raises:
        ApplicationValidationError: If not a string-to-string mapping.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ApplicationValidationError(
            f"metadata_filters must be a mapping, "
            f"got {type(value).__name__}"
        )
    for key, filter_value in value.items():
        if not isinstance(key, str):
            raise ApplicationValidationError(
                f"metadata_filters keys must be non-blank strings, "
                f"got {type(key).__name__}"
            )
        if not key.strip():
            raise ApplicationValidationError(
                "metadata_filters keys must be non-blank strings, got blank str"
            )
        if not isinstance(filter_value, str):
            raise ApplicationValidationError(
                f"metadata_filters values must be strings, "
                f"got {type(filter_value).__name__}"
            )
    return dict(value)


def _require_chunk_count(value: object) -> None:
    """Reject invalid ingest chunk counts.

    Args:
        value (object): Candidate ``chunk_count``.

    Raises:
        ApplicationValidationError: If not a non-negative ``int``.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApplicationValidationError(
            f"chunk_count must be a non-negative integer, "
            f"got {type(value).__name__}"
        )
    if value < 0:
        raise ApplicationValidationError(
            f"chunk_count must be a non-negative integer, got {value}"
        )


@dataclass(frozen=True, slots=True)
class Citation:
    """A provenance pointer suitable for RAG answers.

    Attributes:
        reference (SourceReference): Domain source the citation points at.
        quote (str | None): Optional excerpt shown alongside the citation.
        chunk_index (int | None): Optional non-negative chunk index.
    """

    reference: SourceReference
    quote: str | None = None
    chunk_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, SourceReference):
            raise ApplicationValidationError(
                f"reference must be a SourceReference, "
                f"got {type(self.reference).__name__}"
            )
        if self.quote is not None:
            _require_text(self.quote, "quote")
        _require_chunk_index(self.chunk_index)


@dataclass(frozen=True, slots=True, kw_only=True)
class AskRequest:
    """Input for a prompt-selected ask/analyze use case.

    Keyword-only. ``prompt_key`` became optional while ``query`` stayed
    required, which under positional construction would have let the two swap
    silently — both are non-blank strings, so no validation could catch it.
    Keyword-only construction removes that class of error outright and keeps
    ``query`` genuinely required rather than defaulted to a blank sentinel.

    Attributes:
        query (str): User question or analysis input.
        prompt_key (str | None): Optional identifier of a selected task prompt.
            ``None`` means general grounded chat with no task template.
        grounding_references (Sequence[SourceReference]): Optional provenance
            identifiers supplied by callers or domain packs; the generic
            contract does not interpret their business meaning. Reserved: no
            current use case narrows retrieval with them.
        history (Sequence[Message]): Prior conversation turns.
        retrieval_limit (int | None): Optional positive limit for retrieval.
    """

    query: str
    prompt_key: str | None = None
    grounding_references: Sequence[SourceReference] = ()
    history: Sequence[Message] = ()
    retrieval_limit: int | None = None

    def __post_init__(self) -> None:
        if self.prompt_key is not None:
            _require_text(self.prompt_key, "prompt_key")
        _require_text(self.query, "query")
        grounding_references = _require_sequence(
            self.grounding_references, "grounding_references"
        )
        for index, item in enumerate(grounding_references):
            if not isinstance(item, SourceReference):
                raise ApplicationValidationError(
                    f"grounding_references[{index}] must be a SourceReference, "
                    f"got {type(item).__name__}"
                )
        object.__setattr__(self, "grounding_references", tuple(grounding_references))
        history = _require_sequence(self.history, "history")
        for index, item in enumerate(history):
            if not isinstance(item, Message):
                raise ApplicationValidationError(
                    f"history[{index}] must be a Message, "
                    f"got {type(item).__name__}"
                )
        object.__setattr__(self, "history", tuple(history))
        _require_retrieval_limit(self.retrieval_limit)


@dataclass(frozen=True, slots=True)
class RunMeta:
    """Safe execution metadata for one ask / tool / analysis turn.

    Deliberately carries no answer, query, chunk, or tool-payload text.
    ``AskResponse.answer`` remains the single source of the reply; this type is
    the shared observability contract for logs and UI.

    Attributes:
        model (str | None): Model the adapter actually invoked.
        latency_ms (int | None): Wall-clock duration of the call.
        usage (Usage | None): Token counts and cost, when the provider reports.
        settings (Mapping[str, object]): Generation settings that were applied,
            after the domain allowlist filtered them.
        request_id (str | None): Correlation id for the turn.
        outcome (str | None): ``success``, ``insufficient``, or ``error``.
        hit_count (int | None): Retrieval hits used as evidence.
        query_rewritten (bool | None): Whether rewrite changed the query string.
        citation_count (int | None): Number of citations on the ask response.
        pack (str | None): Pack identifier when a pack routed the turn.
        path (str | None): Route label (``rag``, ``tools``, ``task_prompt``,
            ``analysis``).
        prompt_key (str | None): Selected task prompt key, when any.
        source_type (str | None): Sorted unique source types from hits.
        tools (Sequence[str]): Invoked tool **names** only.
        error_type (str | None): Exception type name on failure — never the
            exception message.
    """

    model: str | None = None
    latency_ms: int | None = None
    usage: Usage | None = None
    settings: Mapping[str, object] = field(default_factory=dict)
    request_id: str | None = None
    outcome: str | None = None
    hit_count: int | None = None
    query_rewritten: bool | None = None
    citation_count: int | None = None
    pack: str | None = None
    path: str | None = None
    prompt_key: str | None = None
    source_type: str | None = None
    tools: Sequence[str] = ()
    error_type: str | None = None

    def __post_init__(self) -> None:
        if self.model is not None:
            _require_text(self.model, "model")
        if self.latency_ms is not None:
            if not isinstance(self.latency_ms, int) or isinstance(
                self.latency_ms, bool
            ):
                raise ApplicationValidationError(
                    f"latency_ms must be a non-negative integer, "
                    f"got {type(self.latency_ms).__name__}"
                )
            if self.latency_ms < 0:
                raise ApplicationValidationError(
                    f"latency_ms must be a non-negative integer, "
                    f"got {self.latency_ms}"
                )
        if self.usage is not None and not isinstance(self.usage, Usage):
            raise ApplicationValidationError(
                f"usage must be a Usage, got {type(self.usage).__name__}"
            )
        if not isinstance(self.settings, Mapping):
            raise ApplicationValidationError(
                f"settings must be a mapping, "
                f"got {type(self.settings).__name__}"
            )
        object.__setattr__(self, "settings", dict(self.settings))
        for name in (
            "request_id",
            "outcome",
            "pack",
            "path",
            "prompt_key",
            "source_type",
            "error_type",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)
        if self.hit_count is not None:
            if not isinstance(self.hit_count, int) or isinstance(
                self.hit_count, bool
            ):
                raise ApplicationValidationError(
                    f"hit_count must be a non-negative integer, "
                    f"got {type(self.hit_count).__name__}"
                )
            if self.hit_count < 0:
                raise ApplicationValidationError(
                    f"hit_count must be a non-negative integer, "
                    f"got {self.hit_count}"
                )
        if self.query_rewritten is not None and not isinstance(
            self.query_rewritten, bool
        ):
            raise ApplicationValidationError(
                f"query_rewritten must be a bool, "
                f"got {type(self.query_rewritten).__name__}"
            )
        if self.citation_count is not None:
            if not isinstance(self.citation_count, int) or isinstance(
                self.citation_count, bool
            ):
                raise ApplicationValidationError(
                    "citation_count must be a non-negative integer, "
                    f"got {type(self.citation_count).__name__}"
                )
            if self.citation_count < 0:
                raise ApplicationValidationError(
                    "citation_count must be a non-negative integer, "
                    f"got {self.citation_count}"
                )
        tools = _require_sequence(self.tools, "tools")
        for index, item in enumerate(tools):
            if not isinstance(item, str):
                raise ApplicationValidationError(
                    f"tools[{index}] must be a non-empty string, "
                    f"got {type(item).__name__}"
                )
            if not item.strip():
                raise ApplicationValidationError(
                    f"tools[{index}] must be a non-empty string, got blank str"
                )
        object.__setattr__(self, "tools", tuple(tools))

    @classmethod
    def from_result(cls, result: AskResult) -> "RunMeta":
        """Project the observability fields of an ``AskResult``, dropping content."""
        return cls(
            model=result.model,
            latency_ms=result.latency_ms,
            usage=result.usage,
            settings=result.settings,
        )


@dataclass(frozen=True, slots=True)
class AskResponse:
    """Output of a prompt-selected ask/analyze use case.

    Attributes:
        answer (str): Model answer text.
        citations (Sequence[Citation]): Sources supporting the answer.
        tool_outputs (Sequence[InvokeToolResponse]): Optional tool results.
        run (RunMeta | None): Safe execution metadata for the turn. May be set
            without a model call (insufficient evidence). ``None`` only when the
            caller did not attach metadata.
        generation_hits (Sequence[ScoredChunk]): Hits that entered the
            generation prompt. Not serialized on HTTP.
    """

    answer: str
    citations: Sequence[Citation] = ()
    tool_outputs: Sequence["InvokeToolResponse"] = ()
    run: RunMeta | None = None
    generation_hits: Sequence[ScoredChunk] = ()

    def __post_init__(self) -> None:
        _require_text(self.answer, "answer")
        if self.run is not None and not isinstance(self.run, RunMeta):
            raise ApplicationValidationError(
                f"run must be a RunMeta, got {type(self.run).__name__}"
            )
        citations = _require_sequence(self.citations, "citations")
        for index, item in enumerate(citations):
            if not isinstance(item, Citation):
                raise ApplicationValidationError(
                    f"citations[{index}] must be a Citation, "
                    f"got {type(item).__name__}"
                )
        object.__setattr__(self, "citations", tuple(citations))
        tool_outputs = _require_sequence(self.tool_outputs, "tool_outputs")
        for index, item in enumerate(tool_outputs):
            if not isinstance(item, InvokeToolResponse):
                raise ApplicationValidationError(
                    f"tool_outputs[{index}] must be an InvokeToolResponse, "
                    f"got {type(item).__name__}"
                )
        object.__setattr__(self, "tool_outputs", tuple(tool_outputs))
        generation_hits = _require_sequence(self.generation_hits, "generation_hits")
        for index, item in enumerate(generation_hits):
            if not isinstance(item, ScoredChunk):
                raise ApplicationValidationError(
                    f"generation_hits[{index}] must be a ScoredChunk, "
                    f"got {type(item).__name__}"
                )
        object.__setattr__(self, "generation_hits", tuple(generation_hits))


@dataclass(frozen=True, slots=True)
class IngestRequest:
    """Input for ingesting knowledge sources.

    Attributes:
        documents (Sequence[SourceDocument]): Knowledge documents to ingest.
    """

    documents: Sequence[SourceDocument] = ()

    def __post_init__(self) -> None:
        documents = _require_sequence(self.documents, "documents")
        for index, item in enumerate(documents):
            if not isinstance(item, SourceDocument):
                raise ApplicationValidationError(
                    f"documents[{index}] must be a SourceDocument, "
                    f"got {type(item).__name__}"
                )
        if not documents:
            raise ApplicationValidationError(
                "documents must contain at least one item"
            )
        object.__setattr__(self, "documents", tuple(documents))


@dataclass(frozen=True, slots=True)
class IngestResponse:
    """Outcome of an ingest request.

    Attributes:
        accepted_ids (Sequence[str]): Non-blank identifiers accepted for ingest.
        chunk_count (int): Total chunks stored for the request. Required with no
            default, so an unreported count cannot be mistaken for zero.
    """

    accepted_ids: Sequence[str]
    chunk_count: int

    def __post_init__(self) -> None:
        accepted_ids = _require_sequence(self.accepted_ids, "accepted_ids")
        for index, item in enumerate(accepted_ids):
            _require_text(item, f"accepted_ids[{index}]")
        object.__setattr__(self, "accepted_ids", tuple(accepted_ids))
        _require_chunk_count(self.chunk_count)


@dataclass(frozen=True, slots=True)
class InvokeToolRequest:
    """Input for invoking a named tool.

    Attributes:
        tool_name (str): Tool identifier matching a registered tool port.
        arguments (Mapping[str, object]): JSON-compatible tool arguments (copied
            into a plain ``dict``).
    """

    tool_name: str
    arguments: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.tool_name, "tool_name")
        if not isinstance(self.arguments, Mapping):
            raise ApplicationValidationError(
                f"arguments must be a mapping, "
                f"got {type(self.arguments).__name__}"
            )
        for key in self.arguments:
            if not isinstance(key, str):
                raise ApplicationValidationError(
                    f"arguments keys must be non-blank strings, "
                    f"got {type(key).__name__}"
                )
            if not key.strip():
                raise ApplicationValidationError(
                    "arguments keys must be non-blank strings, got blank str"
                )
        object.__setattr__(self, "arguments", dict(self.arguments))


@dataclass(frozen=True, slots=True)
class InvokeToolResponse:
    """Outcome of a tool invocation.

    Attributes:
        tool_name (str): Tool that produced the result.
        result (str): Tool output text, matching ``Tool.run``.
    """

    tool_name: str
    result: str

    def __post_init__(self) -> None:
        _require_text(self.tool_name, "tool_name")
        _require_text(self.result, "result")


@dataclass(frozen=True, slots=True)
class RetrieveRequest:
    """Input for metadata-filtered semantic retrieval.

    Attributes:
        query (str): Natural-language query to embed and search with.
        retrieval_limit (int): Positive cap on ranked hits (filter-then-limit).
        metadata_filters (Mapping[str, str] | None): Optional opaque exact-match
            AND filters over ``SourceMetadata.extra``. ``None`` or ``{}`` means
            unfiltered top-k. Copied into a plain ``dict`` when present.
    """

    query: str
    retrieval_limit: int
    metadata_filters: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        _require_text(self.query, "query")
        object.__setattr__(
            self,
            "retrieval_limit",
            _require_positive_retrieval_limit(self.retrieval_limit),
        )
        object.__setattr__(
            self,
            "metadata_filters",
            _require_metadata_filters(self.metadata_filters),
        )


@dataclass(frozen=True, slots=True)
class RetrieveResponse:
    """Outcome of a retrieve request.

    Attributes:
        hits (Sequence[ScoredChunk]): Ranked chunks with full provenance.
    """

    hits: Sequence[ScoredChunk] = ()

    def __post_init__(self) -> None:
        hits = _require_sequence(self.hits, "hits")
        for index, item in enumerate(hits):
            if not isinstance(item, ScoredChunk):
                raise ApplicationValidationError(
                    f"hits[{index}] must be a ScoredChunk, "
                    f"got {type(item).__name__}"
                )
        object.__setattr__(self, "hits", tuple(hits))


@dataclass(frozen=True, slots=True)
class RewriteRetrieveResponse:
    """Outcome of rewrite-then-retrieve.

    Attributes:
        hits (Sequence[ScoredChunk]): Ranked chunks with full provenance.
        original_query (str): The caller's natural-language query before rewrite.
        rewritten_query (str): The retrieval-oriented query that was embedded.
    """

    original_query: str
    rewritten_query: str
    hits: Sequence[ScoredChunk] = ()

    def __post_init__(self) -> None:
        _require_text(self.original_query, "original_query")
        _require_text(self.rewritten_query, "rewritten_query")
        hits = _require_sequence(self.hits, "hits")
        for index, item in enumerate(hits):
            if not isinstance(item, ScoredChunk):
                raise ApplicationValidationError(
                    f"hits[{index}] must be a ScoredChunk, "
                    f"got {type(item).__name__}"
                )
        object.__setattr__(self, "hits", tuple(hits))

    @property
    def was_rewritten(self) -> bool:
        """Whether rewrite changed the query beyond leading/trailing whitespace."""
        return self.original_query.strip() != self.rewritten_query.strip()


class ConnectorSyncStatus(StrEnum):
    """Per-document result of one connector synchronization run."""

    INGESTED = "ingested"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ConnectorSyncOutcome:
    """Outcome for one listed connector document.

    ``error_type`` is an exception class name only; it must never carry
    exception messages or provider payload text.

    Args:
        source_id (str): Connector identity of the listed document.
        status (ConnectorSyncStatus): Ingested, skipped, or failed.
        chunk_count (int): Chunks stored for ingested/skipped rows; ``0`` when failed.
        error_type (str | None): Exception class name when ``status`` is failed.
    """

    source_id: str
    status: ConnectorSyncStatus
    chunk_count: int
    error_type: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        if not isinstance(self.status, ConnectorSyncStatus):
            raise ApplicationValidationError(
                f"status must be a ConnectorSyncStatus, "
                f"got {type(self.status).__name__}"
            )
        _require_chunk_count(self.chunk_count)
        if self.error_type is not None:
            _require_text(self.error_type, "error_type")


@dataclass(frozen=True, slots=True)
class ConnectorSyncResponse:
    """Ordered per-document outcomes of a connector sync run.

    Args:
        outcomes (Sequence[ConnectorSyncOutcome]): Results in listing order.
    """

    outcomes: Sequence[ConnectorSyncOutcome]

    def __post_init__(self) -> None:
        outcomes = _require_sequence(self.outcomes, "outcomes")
        for index, item in enumerate(outcomes):
            if not isinstance(item, ConnectorSyncOutcome):
                raise ApplicationValidationError(
                    f"outcomes[{index}] must be a ConnectorSyncOutcome, "
                    f"got {type(item).__name__}"
                )
        object.__setattr__(self, "outcomes", tuple(outcomes))

    @property
    def ingested_count(self) -> int:
        """Number of documents ingested in this run."""
        return sum(
            1
            for outcome in self.outcomes
            if outcome.status is ConnectorSyncStatus.INGESTED
        )

    @property
    def skipped_count(self) -> int:
        """Number of documents skipped because the revision was unchanged."""
        return sum(
            1
            for outcome in self.outcomes
            if outcome.status is ConnectorSyncStatus.SKIPPED
        )

    @property
    def failed_count(self) -> int:
        """Number of documents that failed without aborting the run."""
        return sum(
            1
            for outcome in self.outcomes
            if outcome.status is ConnectorSyncStatus.FAILED
        )
