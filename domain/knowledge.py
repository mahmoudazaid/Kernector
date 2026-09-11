"""Knowledge-domain entities: sources, provenance, and chunks."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from math import isfinite

from domain.errors import DomainValidationError



class SourceType(StrEnum):
    """Documented well-known source kinds.

    Not a closed validation set for ``SourceReference.source_type`` — connectors
    may introduce other string kinds — but the members below are the stable hub
    and upload vocabulary.
    """

    KNOWLEDGE_DOCUMENT = "knowledge_document"
    GOOGLE_DRIVE = "google_drive"


STORY_SOURCE_TYPES = frozenset({"story", "user_story"})
"""Source kinds treated as user stories by eval and software-delivery scoring."""

HUB_SOURCE_TYPES = frozenset(
    {
        SourceType.KNOWLEDGE_DOCUMENT,
        SourceType.GOOGLE_DRIVE,
    }
)
"""Source kinds shown in the shared documents hub and chunk-inspect API.

Explicit members — not ``frozenset(SourceType)`` — so adding a connector kind
to the enum does not silently widen the hub.
"""


class CatalogStatus(StrEnum):
    """Lifecycle status of a catalogued knowledge document."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    DEGRADED = "degraded"

def _require_text(value: object, field_name: str) -> None:
    """Reject anything that is not a non-blank string.

    The type check runs before the blankness check so a wrong type is reported
    as a wrong type. Fusing the two would report every rejection as "must be
    non-empty", which is false for an ``int`` and hides what actually arrived.
    """
    if not isinstance(value, str):
        raise DomainValidationError(
            f"{field_name} must be a non-empty string, got {type(value).__name__}"
        )
    if not value.strip():
        raise DomainValidationError(f"{field_name} must be non-empty")


def _require_index(value: object, field_name: str) -> None:
    """Reject anything that is not a non-negative integer."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise DomainValidationError(
            f"{field_name} must be a non-negative integer, "
            f"got {type(value).__name__}"
        )
    if value < 0:
        raise DomainValidationError(
            f"{field_name} must be a non-negative integer, got {value}"
        )

def _require_vector(value: object, field_name: str) -> None:
    """Reject anything that is not a non-empty sequence of numbers."""
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise DomainValidationError(
            f"{field_name} must be a sequence of floats, "
            f"got {type(value).__name__}"
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
    source_type: str

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.source_type, "source_type")


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
                f"reference must be a SourceReference, "
                f"got {type(self.reference).__name__}"
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
                f"metadata must be a SourceMetadata, "
                f"got {type(self.metadata).__name__}"
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
                f"metadata must be a SourceMetadata, "
                f"got {type(self.metadata).__name__}"
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


@dataclass(frozen=True, slots=True)
class ChunkPage:
    """One page of stored chunks plus whether more rows exist after this page.

    ``has_more`` is derived from the ordered id set before hydrate drops, so a
    skipped corrupt or vanished row cannot collapse pagination.
    """

    chunks: tuple[DocumentChunk, ...]
    has_more: bool


type Vector = Sequence[float]


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    """A chunk paired with its embedding, so the two cannot drift apart."""

    chunk: DocumentChunk
    vector: Vector

    def __post_init__(self) -> None:
        if not isinstance(self.chunk, DocumentChunk):
            raise DomainValidationError(
                f"chunk must be a DocumentChunk, "
                f"got {type(self.chunk).__name__}"
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
                f"chunk must be a DocumentChunk, "
                f"got {type(self.chunk).__name__}"
            )
        if not isinstance(self.score, (int, float)) or isinstance(self.score, bool):
            raise DomainValidationError(
                f"score must be a finite number, "
                f"got {type(self.score).__name__}"
            )
        if not isfinite(self.score):
            raise DomainValidationError(
                f"score must be a finite number, got {self.score}"
            )


@dataclass(frozen=True, slots=True)
class ConnectorDocument:
    """A provider-neutral listing of one remote knowledge file.

    Args:
        reference (SourceReference): Stable identity used for ingest and catalog rows.
        file_name (str): Remote file name, including any suffix.
        revision (str): Provider revision marker used to skip unchanged files.
        extra (Mapping[str, str]): Opaque connector metadata (MIME type, size, flags).
    """

    reference: SourceReference
    file_name: str
    revision: str
    extra: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.reference, SourceReference):
            raise DomainValidationError(
                "reference must be a SourceReference"
            )
        _require_text(self.file_name, "file_name")
        _require_text(self.revision, "revision")

    @property
    def source_id(self) -> str:
        """The originating source identifier, preserved for traceability."""
        return self.reference.source_id


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
    """Durable metadata for one catalogued knowledge document."""

    reference: SourceReference
    file_name: str
    title: str | None
    content_format: str | None
    status: CatalogStatus
    uploaded_at: datetime
    chunk_count: int
    error: str | None
    revision: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, SourceReference):
            raise DomainValidationError(
                f"reference must be a SourceReference, "
                f"got {type(self.reference).__name__}"
            )
        _require_text(self.file_name, "file_name")
        if not isinstance(self.status, CatalogStatus):
            raise DomainValidationError(
                f"status must be a CatalogStatus, "
                f"got {type(self.status).__name__}"
            )
        if not isinstance(self.uploaded_at, datetime):
            raise DomainValidationError(
                f"uploaded_at must be a datetime, "
                f"got {type(self.uploaded_at).__name__}"
            )
        if self.uploaded_at.tzinfo is None:
            raise DomainValidationError(
                "uploaded_at must be timezone-aware"
            )
        _require_index(self.chunk_count, "chunk_count")
        if self.revision is not None and not isinstance(self.revision, str):
            raise DomainValidationError(
                f"revision must be a string or None, "
                f"got {type(self.revision).__name__}"
            )
