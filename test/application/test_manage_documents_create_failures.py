"""Cycle 5: create-upload failure policies."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from application.ingest_knowledge import IngestKnowledge
from application.manage_documents import ManageUploadedDocuments
from domain.knowledge import (
    CatalogStatus,
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
        ingest=IngestKnowledge(
            StubEmbeddingModel(),
            InMemoryVectorStore(),
            chunk_size=10,
            chunk_overlap=2,
        ),
        vector_store=InMemoryVectorStore(),
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
        ingest=IngestKnowledge(
            FailingEmbeddingModel(),
            store,
            chunk_size=10,
            chunk_overlap=2,
        ),
        vector_store=store,
        new_source_id=FixedIdFactory("id-fail"),
        now=FixedClock(datetime(2026, 8, 28, 12, 0, tzinfo=UTC)),
    )

    with pytest.raises(EmbeddingUnavailable):
        use_case.create(UploadPayload(file_name="guide.md", content=b"x"))

    rows = catalog.all()
    assert len(rows) == 1
    assert rows[0].status is CatalogStatus.FAILED
    assert rows[0].reference.source_id == "id-fail"
    assert rows[0].error
    assert store.records == {}
