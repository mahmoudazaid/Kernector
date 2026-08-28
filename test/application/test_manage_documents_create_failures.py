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
    """Accepts the pending row, then refuses every later write."""

    def __init__(self) -> None:
        super().__init__()
        self.upserts = 0

    def upsert(self, document: CatalogDocument) -> None:
        self.upserts += 1
        if self.upserts > 1:
            raise RuntimeError("catalog upsert failed")
        super().upsert(document)


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
