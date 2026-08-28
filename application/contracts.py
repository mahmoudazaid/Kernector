"""Typed request/response contracts for core use cases.

UI-agnostic DTOs shared by Streamlit and future API clients. Domain entities
are reused; prompt bodies and analysis-specific outputs stay out of scope.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from application.errors import ApplicationValidationError
from domain.knowledge import SourceDocument, SourceReference, Ticket
from domain.models import Message


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


@dataclass(frozen=True, slots=True)
class AskRequest:
    """Input for a prompt-selected ask/analyze use case.

    Attributes:
        prompt_key (str): Identifier of the selected prompt (not its body).
        query (str): User question or analysis input.
        ticket (Ticket | None): Optional ticket to ground the request.
        history (Sequence[Message]): Prior conversation turns.
        retrieval_limit (int | None): Optional positive limit for retrieval.
    """

    prompt_key: str
    query: str
    ticket: Ticket | None = None
    history: Sequence[Message] = ()
    retrieval_limit: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.prompt_key, "prompt_key")
        _require_text(self.query, "query")
        if self.ticket is not None and not isinstance(self.ticket, Ticket):
            raise ApplicationValidationError(
                f"ticket must be a Ticket, got {self.ticket!r}"
            )
        history = _require_sequence(self.history, "history")
        for item in history:
            if not isinstance(item, Message):
                raise ApplicationValidationError(
                    f"history items must be Message, got {item!r}"
                )
        object.__setattr__(self, "history", tuple(history))
        _require_retrieval_limit(self.retrieval_limit)


@dataclass(frozen=True, slots=True)
class AskResponse:
    """Output of a prompt-selected ask/analyze use case.

    Attributes:
        answer (str): Model answer text.
        citations (Sequence[Citation]): Sources supporting the answer.
        tool_outputs (Sequence[InvokeToolResponse]): Optional tool results.
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
