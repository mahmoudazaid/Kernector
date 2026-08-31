"""Cycle 7: ordered delete and partial-failure policies."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from application.ingest_knowledge import IngestKnowledge
from application.manage_documents import (
    DocumentManagementError,
    ManageUploadedDocuments,
    PartialDeleteFailure,
)
from domain.knowledge import (
    CatalogStatus,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
    UploadPayload,
)
from test.document_doubles import (
    FixedClock,
    FixedIdFactory,
    InMemoryDocumentCatalog,
    RecordingExtractor,
)
from test.doubles import InMemoryVectorStore, StubEmbeddingModel

CONTENT = "abcdefghijklmnopqrstuvwxyz"
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024


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


class FailingDeleteStore(InMemoryVectorStore):
    def delete_source(self, reference: SourceReference) -> None:
        raise RuntimeError("vector delete failed")


def _seed(
    catalog: InMemoryDocumentCatalog,
    store: InMemoryVectorStore,
    *,
    source_id: str = "id-1",
) -> SourceReference:
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory(source_id),
        now=FixedClock(datetime(2026, 8, 28, 12, 0, tzinfo=UTC)),
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    )
    return use_case.create(
        UploadPayload(file_name="guide.md", content=b"x")
    ).reference


def test_delete_removes_chunks_then_catalog_row() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    reference = _seed(catalog, store)
    assert catalog.get(reference) is not None
    assert store.records

    ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    ).delete(reference)

    assert catalog.get(reference) is None
    assert store.records == {}


def test_vector_delete_failure_leaves_catalog_unchanged() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    reference = _seed(catalog, store)
    failing_store = FailingDeleteStore()
    failing_store.records = dict(store.records)

    with pytest.raises(DocumentManagementError, match="vector chunks"):
        ManageUploadedDocuments(
            catalog=catalog,
            extractor=RecordingExtractor(document_factory=_document_factory),
            ingest_factory=lambda: IngestKnowledge(
                StubEmbeddingModel(),
                failing_store,
                chunk_size=10,
                chunk_overlap=2,
            ),
            vector_store_factory=lambda: failing_store,
            max_upload_bytes=_MAX_UPLOAD_BYTES,
        ).delete(reference)

    row = catalog.get(reference)
    assert row is not None
    assert row.status is CatalogStatus.READY


def test_catalog_delete_failure_after_vector_success_is_partial() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    reference = _seed(catalog, store)
    catalog.fail_on_delete = True

    with pytest.raises(PartialDeleteFailure, match="catalog row remains"):
        ManageUploadedDocuments(
            catalog=catalog,
            extractor=RecordingExtractor(document_factory=_document_factory),
            ingest_factory=lambda: IngestKnowledge(
                StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
            ),
            vector_store_factory=lambda: store,
            max_upload_bytes=_MAX_UPLOAD_BYTES,
        ).delete(reference)

    assert store.records == {}
    assert catalog.get(reference) is not None


def test_delete_missing_data_is_idempotent_and_retry_converges() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    reference = SourceReference("ghost", SourceType.KNOWLEDGE_DOCUMENT)
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    )
    use_case.delete(reference)
    use_case.delete(reference)
    assert catalog.all() == ()
    assert store.records == {}
