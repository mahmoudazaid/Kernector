"""Knowledge-domain entities: sources, provenance, and chunks."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from math import isfinite

from domain.errors import DomainValidationError



class SourceType(StrEnum):
    """The kinds of knowledge a source can hold."""

    KNOWLEDGE_DOCUMENT = "knowledge_document"


class CatalogStatus(StrEnum):
    """Lifecycle status of an uploaded document in the catalog."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    DEGRADED = "degraded"

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


@dataclass(frozen=True, slots=True)
class UploadPayload:
    """Raw upload bytes and the client-supplied file name."""

    file_name: str
    content: bytes

    def __post_init__(self) -> None:
        _require_text(self.file_name, "file_name")
        if not isinstance(self.content, (bytes, bytearray)):
            raise DomainValidationError(
                f"content must be bytes, got {type(self.content).__name__}"
            )


@dataclass(frozen=True, slots=True)
class CatalogDocument:
    """Durable metadata for one uploaded knowledge document."""

    reference: SourceReference
    file_name: str
    title: str | None
    content_format: str | None
    status: CatalogStatus
    uploaded_at: datetime
    chunk_count: int
    error: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, SourceReference):
            raise DomainValidationError(
                f"reference must be a SourceReference, got {self.reference!r}"
            )
        _require_text(self.file_name, "file_name")
        if not isinstance(self.status, CatalogStatus):
            raise DomainValidationError(
                f"status must be a CatalogStatus, got {self.status!r}"
            )
        if not isinstance(self.uploaded_at, datetime):
            raise DomainValidationError(
                f"uploaded_at must be a datetime, got {self.uploaded_at!r}"
            )
        if self.uploaded_at.tzinfo is None:
            raise DomainValidationError(
                "uploaded_at must be timezone-aware"
            )
        _require_index(self.chunk_count, "chunk_count")
