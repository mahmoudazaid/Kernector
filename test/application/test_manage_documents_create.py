"""Cycle 4: create-upload allocates UUID and reaches ready."""

from __future__ import annotations

from datetime import UTC, datetime

from application.ingest_knowledge import IngestKnowledge
from application.manage_documents import ManageUploadedDocuments
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

CONTENT = "abcdefghijklmnopqrstuvwxyz"  # 3 chunks at size 10 / overlap 2


def _document_factory(
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
        CONTENT,
    )


def _use_case(
    catalog: InMemoryDocumentCatalog,
    *,
    ids: FixedIdFactory | None = None,
    clock: FixedClock | None = None,
    extractor: RecordingExtractor | None = None,
    store: InMemoryVectorStore | None = None,
) -> ManageUploadedDocuments:
    store = store or InMemoryVectorStore()
    ingest = IngestKnowledge(
        StubEmbeddingModel(),
        store,
        chunk_size=10,
        chunk_overlap=2,
    )
    return ManageUploadedDocuments(
        catalog=catalog,
        extractor=extractor
        or RecordingExtractor(document_factory=_document_factory),
        ingest=ingest,
        vector_store=store,
        new_source_id=ids or FixedIdFactory("11111111-1111-1111-1111-111111111111"),
        now=clock
        or FixedClock(datetime(2026, 8, 28, 12, 0, tzinfo=UTC)),
    )


def test_create_persists_application_generated_uuid() -> None:
    catalog = InMemoryDocumentCatalog()
    result = _use_case(
        catalog,
        ids=FixedIdFactory("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
    ).create(UploadPayload(file_name="guide.md", content=b"# Guide\n"))

    assert result.reference.source_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert result.reference.source_type is SourceType.KNOWLEDGE_DOCUMENT
    assert result.status is CatalogStatus.READY
    assert result.chunk_count == 3
    assert catalog.get(result.reference) == result


def test_two_creates_with_same_filename_get_distinct_ids() -> None:
    catalog = InMemoryDocumentCatalog()
    use_case = _use_case(
        catalog,
        ids=FixedIdFactory("id-1", "id-2"),
        clock=FixedClock(
            datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
            datetime(2026, 8, 28, 12, 1, tzinfo=UTC),
            datetime(2026, 8, 28, 12, 2, tzinfo=UTC),
            datetime(2026, 8, 28, 12, 3, tzinfo=UTC),
        ),
    )
    first = use_case.create(UploadPayload(file_name="guide.md", content=b"a"))
    second = use_case.create(UploadPayload(file_name="guide.md", content=b"b"))

    assert first.reference.source_id == "id-1"
    assert second.reference.source_id == "id-2"
    assert first.file_name == second.file_name == "guide.md"
    assert len(catalog.all()) == 2


def test_create_observes_pending_then_ready_transitions() -> None:
    catalog = InMemoryDocumentCatalog()
    statuses: list[CatalogStatus] = []

    class TrackingCatalog(InMemoryDocumentCatalog):
        def upsert(self, document):  # type: ignore[no-untyped-def]
            statuses.append(document.status)
            super().upsert(document)

    tracking = TrackingCatalog()
    result = _use_case(tracking).create(
        UploadPayload(file_name="guide.md", content=b"# Guide\n")
    )

    assert statuses == [CatalogStatus.PENDING, CatalogStatus.READY]
    assert result.status is CatalogStatus.READY
