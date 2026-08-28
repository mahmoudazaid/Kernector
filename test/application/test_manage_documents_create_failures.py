"""Cycle 5: create-upload failure policies."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from application.ingest_knowledge import IngestFailure, IngestKnowledge
from application.manage_documents import ManageUploadedDocuments
from domain.knowledge import (
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
