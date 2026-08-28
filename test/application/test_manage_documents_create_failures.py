"""Cycle 5: create-upload failure policies."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from application.ingest_knowledge import IngestFailure, IngestKnowledge
from application.manage_documents import (
    ManageUploadedDocuments,
    PartialCreateFailure,
)
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    EmbeddedChunk,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    UploadPayload,
)
from test.document_doubles import (
    FixedClock,
    FixedIdFactory,
    InMemoryDocumentCatalog,
    RecordingExtractor,
)
from test.doubles import (
    EmbeddingUnavailable,
    FailingEmbeddingModel,
    InMemoryVectorStore,
    StubEmbeddingModel,
)

CONTENT = "abcdefghijklmnopqrstuvwxyz"


class FailingUpsertStore(InMemoryVectorStore):
    """Deletes successfully then fails on upsert (mutation started)."""

    def upsert(self, embedded: Sequence[EmbeddedChunk]) -> None:
        raise RuntimeError("upsert failed")


class RecoveryRefusingCatalog(InMemoryDocumentCatalog):
    """Accepts the pending row, then refuses every later write.

    ``write_error`` is the exact instance raised, so a test can assert identity
    rather than matching on text.
    """

    def __init__(self, error: Exception | None = None) -> None:
        super().__init__()
        self.upserts = 0
        self.write_error = error or RuntimeError("catalog upsert failed")

    def upsert(self, document: CatalogDocument) -> None:
        self.upserts += 1
        if self.upserts > 1:
            raise self.write_error
        super().upsert(document)


class _ExplodingIngest:
    """Ingest stand-in that raises one known exception instance."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    def execute(self, request: object) -> object:
        raise self._error


def _document_factory(
    payload: UploadPayload, reference: SourceReference
) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            reference,
            title="guide",
            provider="upload",
            content_format="markdown",
            extra={"file_name": payload.file_name},
        ),
        CONTENT,
    )


def test_create_extraction_failure_leaves_no_catalog_row() -> None:
    catalog = InMemoryDocumentCatalog()
    extractor = RecordingExtractor(error=RuntimeError("unreadable upload"))
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        extractor=extractor,
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(),
            InMemoryVectorStore(),
            chunk_size=10,
            chunk_overlap=2,
        ),
        vector_store_factory=InMemoryVectorStore,
        new_source_id=FixedIdFactory("id-1"),
        now=FixedClock(datetime(2026, 8, 28, 12, 0, tzinfo=UTC)),
    )

    with pytest.raises(RuntimeError, match="unreadable upload"):
        use_case.create(UploadPayload(file_name="guide.md", content=b"x"))

    assert catalog.all() == ()


def test_create_ingest_failure_leaves_failed_row_and_propagates_cause() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory),
        ingest_factory=lambda: IngestKnowledge(
            FailingEmbeddingModel(),
            store,
            chunk_size=10,
            chunk_overlap=2,
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("id-fail"),
        now=FixedClock(datetime(2026, 8, 28, 12, 0, tzinfo=UTC)),
    )

    with pytest.raises(IngestFailure) as raised:
        use_case.create(UploadPayload(file_name="guide.md", content=b"x"))

    # The typed failure reaches the caller intact: composition reads its cause
    # to build the store-specific guidance, which an unwrapped cause would lose.
    assert isinstance(raised.value.__cause__, EmbeddingUnavailable)
    assert raised.value.vector_mutation_started is False
    rows = catalog.all()
    assert len(rows) == 1
    assert rows[0].status is CatalogStatus.FAILED
    assert rows[0].reference.source_id == "id-fail"
    assert rows[0].error
    assert store.records == {}


def test_create_records_degraded_when_mutation_may_have_started() -> None:
    """Orphaned chunks must stay visible as state that Delete has to clear."""
    catalog = InMemoryDocumentCatalog()
    store = FailingUpsertStore()
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(),
            store,
            chunk_size=10,
            chunk_overlap=2,
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("id-partial"),
        now=FixedClock(datetime(2026, 8, 28, 12, 0, tzinfo=UTC)),
    )

    with pytest.raises(IngestFailure) as raised:
        use_case.create(UploadPayload(file_name="guide.md", content=b"x"))

    assert raised.value.vector_mutation_started is True
    rows = catalog.all()
    assert len(rows) == 1
    assert rows[0].status is CatalogStatus.DEGRADED
    assert rows[0].error


def test_create_recovery_write_failure_keeps_both_failures() -> None:
    """Losing the ingest error would hide why the upload failed at all."""
    catalog = RecoveryRefusingCatalog()
    store = InMemoryVectorStore()
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory),
        ingest_factory=lambda: IngestKnowledge(
            FailingEmbeddingModel(),
            store,
            chunk_size=10,
            chunk_overlap=2,
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("id-both"),
        now=FixedClock(datetime(2026, 8, 28, 12, 0, tzinfo=UTC)),
    )

    with pytest.raises(PartialCreateFailure) as raised:
        use_case.create(UploadPayload(file_name="guide.md", content=b"x"))

    ingest_error = raised.value.ingest_error
    assert isinstance(ingest_error, IngestFailure)
    assert isinstance(ingest_error.__cause__, EmbeddingUnavailable)
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert str(raised.value.__cause__) == "catalog upsert failed"
    # The pending row is all that survived, so the caller must be told to look.
    rows = catalog.all()
    assert len(rows) == 1
    assert rows[0].status is CatalogStatus.PENDING


def test_create_recovery_write_failure_after_vector_mutation_keeps_both() -> None:
    catalog = RecoveryRefusingCatalog()
    store = FailingUpsertStore()
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(),
            store,
            chunk_size=10,
            chunk_overlap=2,
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("id-both-degraded"),
        now=FixedClock(datetime(2026, 8, 28, 12, 0, tzinfo=UTC)),
    )

    with pytest.raises(PartialCreateFailure) as raised:
        use_case.create(UploadPayload(file_name="guide.md", content=b"x"))

    assert isinstance(raised.value.ingest_error, IngestFailure)
    assert raised.value.ingest_error.vector_mutation_started is True
    assert isinstance(raised.value.__cause__, RuntimeError)


PARTIAL_CREATE_MESSAGE = (
    "Upload failed and its status could not be saved; retry, or delete any "
    "visible pending document."
)

# Stand-ins for the two things that must never surface: a credential carried in
# a vendor error, and a server path carried in an adapter error.
LEAKY_INGEST_ERROR = IngestFailure(
    "openrouter rejected key sk-live-abc123",
    vector_mutation_started=False,
    cause=RuntimeError("vendor said 401 for sk-live-abc123"),
)
LEAKY_CATALOG_ERROR = RuntimeError(
    "could not write catalog at /srv/kernector/data/uploads.json"
)


def _use_case_with_both_failures(
    catalog: RecoveryRefusingCatalog,
) -> ManageUploadedDocuments:
    return ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory),
        ingest_factory=lambda: _ExplodingIngest(LEAKY_INGEST_ERROR),
        vector_store_factory=InMemoryVectorStore,
        new_source_id=FixedIdFactory("id-leak"),
        now=FixedClock(datetime(2026, 8, 28, 12, 0, tzinfo=UTC)),
    )


def test_partial_create_failure_keeps_both_originals_reachable() -> None:
    """The detail must survive for diagnosis — as attributes, not as text."""
    catalog = RecoveryRefusingCatalog(LEAKY_CATALOG_ERROR)

    with pytest.raises(PartialCreateFailure) as raised:
        _use_case_with_both_failures(catalog).create(
            UploadPayload(file_name="guide.md", content=b"x")
        )

    assert raised.value.ingest_error is LEAKY_INGEST_ERROR
    assert raised.value.__cause__ is LEAKY_CATALOG_ERROR


def test_partial_create_failure_message_leaks_neither_failure() -> None:
    """Whoever renders this exception must not have to sanitize it first."""
    catalog = RecoveryRefusingCatalog(LEAKY_CATALOG_ERROR)

    with pytest.raises(PartialCreateFailure) as raised:
        _use_case_with_both_failures(catalog).create(
            UploadPayload(file_name="guide.md", content=b"x")
        )

    message = str(raised.value)
    assert message == PARTIAL_CREATE_MESSAGE
    assert "sk-live-abc123" not in message
    assert "/srv/kernector/data/uploads.json" not in message
    assert str(LEAKY_INGEST_ERROR) not in message
    assert str(LEAKY_CATALOG_ERROR) not in message


def test_partial_create_failure_message_is_fixed_across_causes() -> None:
    """A different pair of failures must not produce a different public string."""
    catalog = RecoveryRefusingCatalog(RuntimeError("disk full on /mnt/data"))
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory),
        ingest_factory=lambda: _ExplodingIngest(
            IngestFailure("other", vector_mutation_started=True)
        ),
        vector_store_factory=InMemoryVectorStore,
        new_source_id=FixedIdFactory("id-other"),
        now=FixedClock(datetime(2026, 8, 28, 12, 0, tzinfo=UTC)),
    )

    with pytest.raises(PartialCreateFailure) as raised:
        use_case.create(UploadPayload(file_name="guide.md", content=b"x"))

    assert str(raised.value) == PARTIAL_CREATE_MESSAGE
    assert "/mnt/data" not in str(raised.value)
