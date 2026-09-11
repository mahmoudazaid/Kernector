"""Cycle 6: explicit replace policies."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
import logging

import pytest

from application.errors import ApplicationValidationError, UploadTooLargeError
from application.ingest_knowledge import IngestFailure, IngestKnowledge
from application.manage_documents import (
    ManageUploadedDocuments,
    UnknownDocumentError,
)
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    EmbeddedChunk,
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
from test.doubles import (
    EmbeddingUnavailable,
    FailingEmbeddingModel,
    InMemoryVectorStore,
    StubEmbeddingModel,
    WrongLengthEmbeddingModel,
)
from test.log_record import operation_payload, operation_records

CONTENT_V1 = "abcdefghijklmnopqrstuvwxyz"
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
CONTENT_V2 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _reference(source_id: str = "id-1") -> SourceReference:
    return SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)


def _document_factory(content: str):
    def factory(
        payload: UploadPayload, reference: SourceReference
    ) -> SourceDocument:
        return SourceDocument(
            SourceMetadata(
                reference,
                title=payload.file_name.rsplit(".", 1)[0],
                provider="upload",
                content_format="markdown",
                extra={"file_name": payload.file_name},
            ),
            content,
        )

    return factory


class FailingUpsertStore(InMemoryVectorStore):
    """Deletes successfully then fails on upsert (mutation started)."""

    def upsert(self, embedded: Sequence[EmbeddedChunk]) -> None:
        raise RuntimeError("upsert failed")


def _seed_ready(
    catalog: InMemoryDocumentCatalog,
    store: InMemoryVectorStore,
    *,
    blob_store: InMemoryUploadBlobStore | None = None,
    source_id: str = "id-1",
    file_name: str = "guide.md",
) -> CatalogDocument:
    blob_store = blob_store or InMemoryUploadBlobStore()
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        blob_store=blob_store,
        extractor=RecordingExtractor(document_factory=_document_factory(CONTENT_V1)),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(),
            store,
            chunk_size=10,
            chunk_overlap=2,
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory(source_id),
        now=FixedClock(datetime(2026, 8, 28, 12, 0, tzinfo=UTC)),
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    )
    return use_case.create(UploadPayload(file_name=file_name, content=b"v1"))


def test_replace_rejects_unknown_id(caplog: pytest.LogCaptureFixture) -> None:
    sentinel = "MISSING-DOC-LEAK-SENTINEL"
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        blob_store=InMemoryUploadBlobStore(),
        extractor=RecordingExtractor(document_factory=_document_factory(CONTENT_V2)),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("unused"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    )
    with caplog.at_level(logging.ERROR, logger="application.manage_documents"):
        with pytest.raises(UnknownDocumentError) as raised:
            use_case.replace(
                _reference(sentinel),
                UploadPayload(file_name="other.md", content=b"x"),
            )
    message = str(raised.value)
    assert sentinel not in message
    assert message == "unknown document"
    assert raised.value.source_id == sentinel
    assert raised.value.source_type == SourceType.KNOWLEDGE_DOCUMENT
    records = operation_records(caplog.records, operation="replace")
    assert len(records) == 1
    payload = operation_payload(records[0])
    assert payload["outcome"] == "error"
    assert payload["error_type"] == "UnknownDocumentError"
    assert payload["source_id"] == sentinel


def test_replace_preserves_source_id_and_updates_metadata() -> None:
    catalog = InMemoryDocumentCatalog()
    blob_store = InMemoryUploadBlobStore()
    store = InMemoryVectorStore()
    original = _seed_ready(catalog, store, blob_store=blob_store)
    before_count = len(store.records)

    use_case = ManageUploadedDocuments(
        catalog=catalog,
        blob_store=blob_store,
        extractor=RecordingExtractor(document_factory=_document_factory(CONTENT_V2)),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("should-not-be-used"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    )
    replaced = use_case.replace(
        original.reference,
        UploadPayload(file_name="guide-v2.md", content=b"v2"),
    )

    assert replaced.reference == original.reference
    assert replaced.file_name == "guide-v2.md"
    assert replaced.status is CatalogStatus.READY
    assert replaced.chunk_count == 3
    assert len(store.records) == before_count
    assert blob_store.get(original.reference) == UploadPayload(
        file_name="guide-v2.md", content=b"v2"
    )
    stored_text = {record.chunk.content for record in store.records.values()}
    assert "ABCDEFGHIJ" in stored_text
    assert "abcdefghij" not in stored_text


def test_replace_failure_before_vector_mutation_leaves_previous_blob_and_previous_row() -> None:
    catalog = InMemoryDocumentCatalog()
    blob_store = InMemoryUploadBlobStore()
    store = InMemoryVectorStore()
    original = _seed_ready(catalog, store, blob_store=blob_store)
    previous_blob = blob_store.get(original.reference)

    use_case = ManageUploadedDocuments(
        catalog=catalog,
        blob_store=blob_store,
        extractor=RecordingExtractor(document_factory=_document_factory(CONTENT_V2)),
        ingest_factory=lambda: IngestKnowledge(
            FailingEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("unused"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    )
    with pytest.raises(IngestFailure) as raised:
        use_case.replace(
            original.reference,
            UploadPayload(file_name="guide-v2.md", content=b"v2"),
        )

    assert raised.value.vector_mutation_started is False
    assert isinstance(raised.value.__cause__, EmbeddingUnavailable)
    restored = catalog.get(original.reference)
    assert restored is not None
    assert restored.status is CatalogStatus.READY
    assert restored.file_name == original.file_name
    assert restored.chunk_count == original.chunk_count
    assert blob_store.get(original.reference) == previous_blob


def test_replace_validation_failure_leaves_previous_blob() -> None:
    """A pre-mutation validation error must not overwrite a working ready row."""
    catalog = InMemoryDocumentCatalog()
    blob_store = InMemoryUploadBlobStore()
    store = InMemoryVectorStore()
    original = _seed_ready(catalog, store, blob_store=blob_store)
    previous_blob = blob_store.get(original.reference)

    use_case = ManageUploadedDocuments(
        catalog=catalog,
        blob_store=blob_store,
        extractor=RecordingExtractor(document_factory=_document_factory(CONTENT_V2)),
        # One vector short of the chunk count: `IngestKnowledge` rejects the
        # batch before its first `delete_source`, so nothing was mutated.
        ingest_factory=lambda: IngestKnowledge(
            WrongLengthEmbeddingModel(-1), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("unused"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    )
    with pytest.raises(ApplicationValidationError):
        use_case.replace(
            original.reference,
            UploadPayload(file_name="guide-v2.md", content=b"v2"),
        )

    restored = catalog.get(original.reference)
    assert restored is not None
    assert restored.status is CatalogStatus.READY
    assert restored.file_name == original.file_name
    assert restored.chunk_count == original.chunk_count
    assert restored.error is None
    # The previous version's chunks were never touched, so the row is truthful.
    assert len(store.records) == original.chunk_count
    assert blob_store.get(original.reference) == previous_blob


def test_degraded_replace_stores_new_blob() -> None:
    catalog = InMemoryDocumentCatalog()
    store = FailingUpsertStore()
    # Seed via catalog only — store upserts will fail during replace.
    reference = _reference("id-1")
    previous = CatalogDocument(
        reference=reference,
        file_name="guide.md",
        title="guide",
        content_format="markdown",
        status=CatalogStatus.READY,
        uploaded_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        chunk_count=3,
        error=None,
    )
    catalog.upsert(previous)
    blob_store = InMemoryUploadBlobStore()
    blob_store.put(reference, UploadPayload(file_name="guide.md", content=b"v1"))

    use_case = ManageUploadedDocuments(
        catalog=catalog,
        blob_store=blob_store,
        extractor=RecordingExtractor(document_factory=_document_factory(CONTENT_V2)),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("unused"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    )
    with pytest.raises(IngestFailure) as raised:
        use_case.replace(
            reference,
            UploadPayload(file_name="guide-v2.md", content=b"v2"),
        )

    assert raised.value.vector_mutation_started is True
    current = catalog.get(reference)
    assert current is not None
    assert current.status is CatalogStatus.DEGRADED
    assert current.file_name == "guide-v2.md"
    assert current.error
    assert blob_store.get(reference) == UploadPayload(
        file_name="guide-v2.md", content=b"v2"
    )


def test_replace_unknown_document_wins_over_oversize() -> None:
    """Unknown-document is checked before size; oversize is not the signal."""
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    extractor = RecordingExtractor(document_factory=_document_factory(CONTENT_V2))
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        blob_store=InMemoryUploadBlobStore(),
        extractor=extractor,
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("unused"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
        max_upload_bytes=16,
    )
    missing = SourceReference("missing", SourceType.KNOWLEDGE_DOCUMENT)

    with pytest.raises(UnknownDocumentError):
        use_case.replace(
            missing,
            UploadPayload(file_name="big.md", content=b"x" * 17),
        )

    assert extractor.calls == []


def test_oversized_replace_is_rejected_before_extract() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    original = _seed_ready(catalog, store)
    extractor = RecordingExtractor(document_factory=_document_factory(CONTENT_V2))
    limit = 16
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        blob_store=InMemoryUploadBlobStore(),
        extractor=extractor,
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("unused"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
        max_upload_bytes=limit,
    )

    with pytest.raises(UploadTooLargeError, match="at most 16 bytes") as raised:
        use_case.replace(
            original.reference,
            UploadPayload(file_name="big.md", content=b"x" * (limit + 1)),
        )

    assert raised.value.limit_bytes == limit
    assert raised.value.actual_bytes == limit + 1
    assert extractor.calls == []
    current = catalog.get(original.reference)
    assert current is not None
    assert current.status is CatalogStatus.READY
    assert current.file_name == original.file_name


def test_replace_blob_put_and_delete_failure_keeps_ready_with_missing_blob_note() -> None:
    """After successful ingest, catalog stays on the new READY row even if
    both blob put and compensating delete fail — do not restore stale metadata.
    """
    from application.manage_documents import MISSING_UPLOAD_BLOB_ERROR

    catalog = InMemoryDocumentCatalog()
    blob_store = InMemoryUploadBlobStore()
    store = InMemoryVectorStore()
    original = _seed_ready(catalog, store, blob_store=blob_store)
    blob_store.fail_on_put = True
    blob_store.fail_on_delete = True

    use_case = ManageUploadedDocuments(
        catalog=catalog,
        blob_store=blob_store,
        extractor=RecordingExtractor(document_factory=_document_factory(CONTENT_V2)),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("unused"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    )
    replaced = use_case.replace(
        original.reference,
        UploadPayload(file_name="guide-v2.md", content=b"v2"),
    )

    assert replaced.status is CatalogStatus.READY
    assert replaced.file_name == "guide-v2.md"
    assert replaced.error == MISSING_UPLOAD_BLOB_ERROR
    # Old bytes may remain on disk when delete also fails; catalog must still
    # describe the new ingest (and mark preview unavailable).
    assert blob_store.get(original.reference) == UploadPayload(
        file_name="guide.md", content=b"v1"
    )


def test_degraded_replace_clears_stale_blob_when_put_fails() -> None:
    from application.manage_documents import MISSING_UPLOAD_BLOB_ERROR

    catalog = InMemoryDocumentCatalog()
    store = FailingUpsertStore()
    reference = _reference("id-1")
    previous = CatalogDocument(
        reference=reference,
        file_name="guide.md",
        title="guide",
        content_format="markdown",
        status=CatalogStatus.READY,
        uploaded_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        chunk_count=3,
        error=None,
    )
    catalog.upsert(previous)
    blob_store = InMemoryUploadBlobStore()
    blob_store.put(reference, UploadPayload(file_name="guide.md", content=b"v1"))
    blob_store.fail_on_put = True

    use_case = ManageUploadedDocuments(
        catalog=catalog,
        blob_store=blob_store,
        extractor=RecordingExtractor(document_factory=_document_factory(CONTENT_V2)),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("unused"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    )
    with pytest.raises(IngestFailure):
        use_case.replace(
            reference,
            UploadPayload(file_name="report.pdf", content=b"%PDF"),
        )

    current = catalog.get(reference)
    assert current is not None
    assert current.status is CatalogStatus.DEGRADED
    assert current.file_name == "report.pdf"
    assert MISSING_UPLOAD_BLOB_ERROR in (current.error or "")
    assert blob_store.get(reference) is None
