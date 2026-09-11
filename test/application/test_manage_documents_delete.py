"""Cycle 7: ordered delete and partial-failure policies."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from application.ingest_knowledge import IngestKnowledge
from application.manage_documents import (
    DocumentManagementError,
    ManageUploadedDocuments,
    PartialDeleteFailure,
    VectorDeleteFailure,
)
from domain.knowledge import (
    CatalogDocument,
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
    InMemoryUploadBlobStore,
    RecordingExtractor,
)
from test.doubles import InMemoryVectorStore, StubEmbeddingModel
from test.log_record import operation_payload, operation_records

CONTENT = "abcdefghijklmnopqrstuvwxyz"
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
VECTOR_DELETE_MESSAGE = VectorDeleteFailure.MESSAGE
PARTIAL_DELETE_MESSAGE = PartialDeleteFailure.MESSAGE
LEAKY_VECTOR_ERROR = RuntimeError(
    "chroma: cannot open /srv/secrets/chroma.sqlite3 (token sk-live-abc123)"
)
LEAKY_CATALOG_ERROR = RuntimeError(
    "could not write catalog at /srv/kernector/data/uploads.json"
)


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
    def __init__(self, error: BaseException | None = None) -> None:
        super().__init__()
        self._error = error or RuntimeError("vector delete failed")

    def delete_source(self, reference: SourceReference) -> None:
        raise self._error


class LeakyDeleteCatalog(InMemoryDocumentCatalog):
    def delete(self, reference: SourceReference) -> None:
        raise LEAKY_CATALOG_ERROR


def _seed(
    catalog: InMemoryDocumentCatalog,
    store: InMemoryVectorStore,
    *,
    blob_store: InMemoryUploadBlobStore | None = None,
    source_id: str = "id-1",
) -> SourceReference:
    blob_store = blob_store or InMemoryUploadBlobStore()
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        blob_store=blob_store,
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


def _use_case(
    catalog: InMemoryDocumentCatalog,
    store: InMemoryVectorStore,
    blob_store: InMemoryUploadBlobStore | None = None,
) -> ManageUploadedDocuments:
    return ManageUploadedDocuments(
        catalog=catalog,
        blob_store=blob_store or InMemoryUploadBlobStore(),
        extractor=RecordingExtractor(document_factory=_document_factory),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    )


def test_delete_removes_blob_catalog_and_vectors() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    blob_store = InMemoryUploadBlobStore()
    reference = _seed(catalog, store, blob_store=blob_store)
    assert catalog.get(reference) is not None
    assert store.records
    assert blob_store.get(reference) == UploadPayload(
        file_name="guide.md", content=b"x"
    )

    _use_case(catalog, store, blob_store).delete(reference)

    assert catalog.get(reference) is None
    assert store.records == {}
    assert blob_store.get(reference) is None


def test_vector_delete_failure_leaves_catalog_unchanged() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    reference = _seed(catalog, store)
    failing_store = FailingDeleteStore()
    failing_store.records = dict(store.records)

    with pytest.raises(DocumentManagementError, match="vector chunks"):
        _use_case(catalog, failing_store).delete(reference)

    row = catalog.get(reference)
    assert row is not None
    assert row.status is CatalogStatus.READY


def test_vector_delete_failure_message_leaks_neither_locator_nor_vendor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinel = "CALLER-DOC-ID-LEAK-SENTINEL"
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    reference = _seed(catalog, store, source_id=sentinel)
    failing_store = FailingDeleteStore(LEAKY_VECTOR_ERROR)
    failing_store.records = dict(store.records)

    with caplog.at_level(logging.ERROR, logger="application.manage_documents"):
        with pytest.raises(VectorDeleteFailure) as raised:
            _use_case(catalog, failing_store).delete(reference)

    message = str(raised.value)
    assert message == VECTOR_DELETE_MESSAGE
    assert sentinel not in message
    assert "sk-live-abc123" not in message
    assert "/srv/secrets" not in message
    assert raised.value.source_id == sentinel
    assert raised.value.delete_error is LEAKY_VECTOR_ERROR
    records = operation_records(caplog.records, operation="delete")
    assert len(records) == 1
    payload = operation_payload(records[0])
    assert payload["outcome"] == "error"
    assert payload["error_type"] == "VectorDeleteFailure"
    assert payload["source_id"] == sentinel


def test_catalog_delete_failure_after_vector_success_is_partial() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    reference = _seed(catalog, store)
    catalog.fail_on_delete = True

    with pytest.raises(PartialDeleteFailure, match="catalog row remains"):
        _use_case(catalog, store).delete(reference)

    assert store.records == {}
    assert catalog.get(reference) is not None


def test_partial_delete_failure_message_leaks_neither_locator_nor_vendor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinel = "CALLER-DOC-ID-LEAK-SENTINEL"
    catalog = LeakyDeleteCatalog()
    store = InMemoryVectorStore()
    reference = _seed(catalog, store, source_id=sentinel)

    with caplog.at_level(logging.ERROR, logger="application.manage_documents"):
        with pytest.raises(PartialDeleteFailure) as raised:
            _use_case(catalog, store).delete(reference)

    message = str(raised.value)
    assert message == PARTIAL_DELETE_MESSAGE
    assert sentinel not in message
    assert "/srv/kernector" not in message
    assert raised.value.source_id == sentinel
    assert raised.value.delete_error is LEAKY_CATALOG_ERROR
    records = operation_records(caplog.records, operation="delete")
    assert len(records) == 1
    payload = operation_payload(records[0])
    assert payload["outcome"] == "error"
    assert payload["error_type"] == "PartialDeleteFailure"
    assert payload["source_id"] == sentinel


def test_delete_does_not_guess_type_from_source_id_alone() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    drive_ref = SourceReference("drive-file-1", SourceType.GOOGLE_DRIVE)
    catalog.upsert(
        CatalogDocument(
            reference=drive_ref,
            file_name="notes.md",
            title="notes",
            content_format="markdown",
            status=CatalogStatus.READY,
            uploaded_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
            chunk_count=1,
            error=None,
            revision="1",
        )
    )

    _use_case(catalog, store).delete(
        SourceReference("drive-file-1", SourceType.KNOWLEDGE_DOCUMENT)
    )

    assert catalog.get(drive_ref) is not None


def test_delete_missing_data_is_idempotent_and_retry_converges() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    reference = SourceReference("ghost", SourceType.KNOWLEDGE_DOCUMENT)
    use_case = _use_case(catalog, store)
    use_case.delete(reference)
    use_case.delete(reference)
    assert catalog.all() == ()
    assert store.records == {}
