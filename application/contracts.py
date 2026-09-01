"""Typed request/response contracts for core use cases.

UI-agnostic DTOs shared by Streamlit and future API clients. Domain entities
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

    Args:
        value (object): Candidate field value.
        field_name (str): Name used in the error message.

    Returns:
        str: The validated string.

    Raises:
        ApplicationValidationError: If ``value`` is blank or not a string.
    """
    if not isinstance(value, str) or not value.strip():
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
            f"{field_name} must be a sequence, got {value!r}"
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
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ApplicationValidationError(
            f"chunk_index must be a non-negative integer, got {value!r}"
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
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ApplicationValidationError(
            f"retrieval_limit must be a positive integer, got {value!r}"
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
            f"retrieval_limit must be a positive integer, got {value!r}"
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
            f"metadata_filters must be a mapping, got {value!r}"
        )
    for key, filter_value in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ApplicationValidationError(
                f"metadata_filters keys must be non-blank strings, got {key!r}"
            )
        if not isinstance(filter_value, str):
            raise ApplicationValidationError(
                f"metadata_filters values must be strings, got {filter_value!r}"
            )
    return dict(value)


def _require_chunk_count(value: object) -> None:
    """Reject invalid ingest chunk counts.

    Args:
        value (object): Candidate ``chunk_count``.

    Raises:
        ApplicationValidationError: If not a non-negative ``int``.
    """
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ApplicationValidationError(
            f"chunk_count must be a non-negative integer, got {value!r}"
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
                f"reference must be a SourceReference, got {self.reference!r}"
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
        for item in grounding_references:
            if not isinstance(item, SourceReference):
                raise ApplicationValidationError(
                    f"grounding_references items must be SourceReference, got {item!r}"
                )
        object.__setattr__(self, "grounding_references", tuple(grounding_references))
        history = _require_sequence(self.history, "history")
        for item in history:
            if not isinstance(item, Message):
                raise ApplicationValidationError(
                    f"history items must be Message, got {item!r}"
                )
        object.__setattr__(self, "history", tuple(history))
        _require_retrieval_limit(self.retrieval_limit)


@dataclass(frozen=True, slots=True)
class RunMeta:
    """Observability for one model call: what ran, how long, at what cost.

    Deliberately carries no answer text. ``AskResponse.answer`` is the single
    source of the reply; reusing ``AskResult`` here would put a second copy of
    the content on the response, free to drift from the first.

    Attributes:
        model (str | None): Model the adapter actually invoked.
        latency_ms (int | None): Wall-clock duration of the call.
        usage (Usage | None): Token counts and cost, when the provider reports.
        settings (Mapping[str, object]): Generation settings that were applied,
            after the domain allowlist filtered them.
    """

    model: str | None = None
    latency_ms: int | None = None
    usage: Usage | None = None
    settings: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.model is not None:
            _require_text(self.model, "model")
        if self.latency_ms is not None and (
            not isinstance(self.latency_ms, int)
            or isinstance(self.latency_ms, bool)
            or self.latency_ms < 0
        ):
            raise ApplicationValidationError(
                f"latency_ms must be a non-negative integer, got {self.latency_ms!r}"
            )
        if self.usage is not None and not isinstance(self.usage, Usage):
            raise ApplicationValidationError(
                f"usage must be a Usage, got {self.usage!r}"
            )
        if not isinstance(self.settings, Mapping):
            raise ApplicationValidationError(
                f"settings must be a mapping, got {self.settings!r}"
            )
        object.__setattr__(self, "settings", dict(self.settings))

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
        run (RunMeta | None): Observability for the model call. ``None`` when no
            call was made — the insufficient-evidence path short-circuits before
            the model, so presentation must tolerate its absence.
    """

    answer: str
    citations: Sequence[Citation] = ()
    tool_outputs: Sequence["InvokeToolResponse"] = ()
    run: RunMeta | None = None

    def __post_init__(self) -> None:
        _require_text(self.answer, "answer")
        if self.run is not None and not isinstance(self.run, RunMeta):
            raise ApplicationValidationError(
                f"run must be a RunMeta, got {self.run!r}"
            )
        citations = _require_sequence(self.citations, "citations")
        for item in citations:
            if not isinstance(item, Citation):
                raise ApplicationValidationError(
                    f"citations items must be Citation, got {item!r}"
                )
        object.__setattr__(self, "citations", tuple(citations))
        tool_outputs = _require_sequence(self.tool_outputs, "tool_outputs")
        for item in tool_outputs:
            if not isinstance(item, InvokeToolResponse):
                raise ApplicationValidationError(
                    f"tool_outputs items must be InvokeToolResponse, got {item!r}"
                )
        object.__setattr__(self, "tool_outputs", tuple(tool_outputs))


class SoftwareDeliveryIntent(StrEnum):
    """User intent selecting which Software Delivery tools to run."""

    RISK_SCORE = "risk_score"
    GENERATE_TESTS = "generate_tests"
    GENERATE_AND_EXPORT = "generate_and_export"


_OUTPUT_STYLES = frozenset({"steps", "gherkin"})


@dataclass(frozen=True, slots=True, kw_only=True)
class OrchestrateSoftwareDeliveryRequest:
    """Input for Software Delivery tool orchestration from retrieved evidence.

    Attributes:
        intent (SoftwareDeliveryIntent): Which tool chain to run.
        target (str): Assessment subject forwarded to tools as ``target``.
        query (str): Natural-language query used for retrieval.
        output_style (str): Opaque generate/export style (``steps`` or ``gherkin``).
        retrieval_limit (int | None): Optional positive limit for retrieval.
    """

    intent: SoftwareDeliveryIntent
    target: str
    query: str
    output_style: str = "steps"
    retrieval_limit: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.intent, SoftwareDeliveryIntent):
            raise ApplicationValidationError(
                f"intent must be a SoftwareDeliveryIntent, got {self.intent!r}"
            )
        _require_text(self.target, "target")
        _require_text(self.query, "query")
        if (
            not isinstance(self.output_style, str)
            or self.output_style not in _OUTPUT_STYLES
        ):
            raise ApplicationValidationError(
                f"output_style must be one of {sorted(_OUTPUT_STYLES)}, "
                f"got {self.output_style!r}"
            )
        _require_retrieval_limit(self.retrieval_limit)


@dataclass(frozen=True, slots=True)
class OrchestrateSoftwareDeliveryResponse:
    """Outcome of Software Delivery tool orchestration.

    Attributes:
        answer (str): Deterministic summary of what ran; not a model reply.
        citations (Sequence[Citation]): Provenance from relevant retrieval hits.
        tool_outputs (Sequence[InvokeToolResponse]): Ordered tool results.
    """

    answer: str
    citations: Sequence[Citation] = ()
    tool_outputs: Sequence["InvokeToolResponse"] = ()

    def __post_init__(self) -> None:
        _require_text(self.answer, "answer")
        citations = _require_sequence(self.citations, "citations")
        for item in citations:
            if not isinstance(item, Citation):
                raise ApplicationValidationError(
                    f"citations items must be Citation, got {item!r}"
                )
        object.__setattr__(self, "citations", tuple(citations))
        tool_outputs = _require_sequence(self.tool_outputs, "tool_outputs")
        for item in tool_outputs:
            if not isinstance(item, InvokeToolResponse):
                raise ApplicationValidationError(
                    f"tool_outputs items must be InvokeToolResponse, got {item!r}"
                )
        object.__setattr__(self, "tool_outputs", tuple(tool_outputs))


@dataclass(frozen=True, slots=True)
class IngestRequest:
    """Input for ingesting knowledge sources.

    Attributes:
        documents (Sequence[SourceDocument]): Knowledge documents to ingest.
    """

    documents: Sequence[SourceDocument] = ()

    def __post_init__(self) -> None:
        documents = _require_sequence(self.documents, "documents")
        for item in documents:
            if not isinstance(item, SourceDocument):
                raise ApplicationValidationError(
                    f"documents items must be SourceDocument, got {item!r}"
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
        for item in accepted_ids:
            _require_text(item, "accepted_ids item")
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
                f"arguments must be a mapping, got {self.arguments!r}"
            )
        for key in self.arguments:
            if not isinstance(key, str) or not key.strip():
                raise ApplicationValidationError(
                    f"arguments keys must be non-blank strings, got {key!r}"
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
        for item in hits:
            if not isinstance(item, ScoredChunk):
                raise ApplicationValidationError(
                    f"hits items must be ScoredChunk, got {item!r}"
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
        for item in hits:
            if not isinstance(item, ScoredChunk):
                raise ApplicationValidationError(
                    f"hits items must be ScoredChunk, got {item!r}"
                )
        object.__setattr__(self, "hits", tuple(hits))
