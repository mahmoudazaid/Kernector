"""Knowledge-domain entities: sources, provenance, and chunks."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite

from domain.errors import DomainValidationError



class SourceType(StrEnum):
    """The kinds of knowledge a source can hold."""

    TICKET = "ticket"
    KNOWLEDGE_DOCUMENT = "knowledge_document"

def _require_text(value: str, field_name: str) -> None:
    """Reject anything that is not a non-blank string."""
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{field_name} must be non-empty")


def _require_source_type(value: object) -> None:
    """Reject source types outside the supported enum."""
    if not isinstance(value, SourceType):
        raise DomainValidationError(
            f"source_type must be a SourceType, got {value!r}"
        )

def _require_index(value: object, field_name: str) -> None:
    """Reject anything that is not a non-negative integer."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DomainValidationError(
            f"{field_name} must be a non-negative integer, got {value!r}"
        )

def _require_vector(value: object, field_name: str) -> None:
    """Reject anything that is not a non-empty sequence of numbers."""
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise DomainValidationError(
            f"{field_name} must be a sequence of floats, got {value!r}"
        )
    if len(value) == 0:
        raise DomainValidationError(f"{field_name} must be non-empty")
    if any(
        not isinstance(item, (int, float)) or isinstance(item, bool) for item in value
    ):
        raise DomainValidationError(f"{field_name} must contain only numeric values")

@dataclass(frozen=True, slots=True)
class SourceReference:
    """Points back at the source a chunk or citation came from."""

    source_id: str
    source_type: SourceType

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_source_type(self.source_type)


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Descriptive metadata about a source, carrying its provenance."""

    reference: SourceReference
    title: str | None = None
    provider: str | None = None
    content_format: str | None = None
    extra: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.reference, SourceReference):
            raise DomainValidationError(
                f"reference must be a SourceReference, got {self.reference!r}"
            )

    @property
    def source_id(self) -> str:
        """The originating source identifier, preserved for traceability."""
        return self.reference.source_id

@dataclass(frozen=True, slots=True)
class Ticket:
    """A work item whose text is the subject of analysis."""

    ticket_id: str
    content: str
    title: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.ticket_id, "ticket_id")
        _require_text(self.content, "content")

    @property
    def reference(self) -> SourceReference:
        """Provenance pointer for citing this ticket."""
        return SourceReference(self.ticket_id, SourceType.TICKET)

@dataclass(frozen=True, slots=True)
class SourceDocument:
    """A knowledge document available for retrieval."""

    metadata: SourceMetadata
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, SourceMetadata):
            raise DomainValidationError(
                f"metadata must be a SourceMetadata, got {self.metadata!r}"
            )
        _require_text(self.content, "content")

    @property
    def reference(self) -> SourceReference:
        """Provenance pointer for citing this document."""
        return self.metadata.reference

    @property
    def source_id(self) -> str:
        """The originating source identifier, preserved for traceability."""
        return self.metadata.source_id

@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """A retrievable slice of a source document."""

    metadata: SourceMetadata
    index: int
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, SourceMetadata):
            raise DomainValidationError(
                f"metadata must be a SourceMetadata, got {self.metadata!r}"
            )
        _require_index(self.index, "index")
        _require_text(self.content, "content")

    @property
    def reference(self) -> SourceReference:
        """Provenance pointer for citing this chunk."""
        return self.metadata.reference

    @property
    def source_id(self) -> str:
        """The originating source identifier, preserved for traceability."""
        return self.metadata.source_id

type Vector = Sequence[float]


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    """A chunk paired with its embedding, so the two cannot drift apart."""

    chunk: DocumentChunk
    vector: Vector

    def __post_init__(self) -> None:
        if not isinstance(self.chunk, DocumentChunk):
            raise DomainValidationError(
                f"chunk must be a DocumentChunk, got {self.chunk!r}"
            )
        _require_vector(self.vector, "vector")

@dataclass(frozen=True, slots=True)
class ScoredChunk:
    """A retrieved chunk and how well it matched the query."""

    chunk: DocumentChunk
    score: float

    def __post_init__(self) -> None:
        if not isinstance(self.chunk, DocumentChunk):
            raise DomainValidationError(
                f"chunk must be a DocumentChunk, got {self.chunk!r}"
            )
        if (
            not isinstance(self.score, (int, float))
            or isinstance(self.score, bool)
            or not isfinite(self.score)
        ):
            raise DomainValidationError(
                f"score must be a finite number, got {self.score!r}"
            )
