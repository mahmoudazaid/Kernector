"""Cycle 6: explicit replace policies."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from application.errors import ApplicationValidationError
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
    RecordingExtractor,
)
from test.doubles import (
    EmbeddingUnavailable,
    FailingEmbeddingModel,
    InMemoryVectorStore,
    StubEmbeddingModel,
    WrongLengthEmbeddingModel,
)

CONTENT_V1 = "abcdefghijklmnopqrstuvwxyz"
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
    source_id: str = "id-1",
    file_name: str = "guide.md",
) -> CatalogDocument:
    use_case = ManageUploadedDocuments(
        catalog=catalog,
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
    )
    return use_case.create(UploadPayload(file_name=file_name, content=b"v1"))


def test_replace_rejects_unknown_id() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    use_case = ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory(CONTENT_V2)),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("unused"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
    )
    with pytest.raises(UnknownDocumentError):
        use_case.replace(
            _reference("missing"),
            UploadPayload(file_name="other.md", content=b"x"),
        )


def test_replace_preserves_source_id_and_updates_metadata() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    original = _seed_ready(catalog, store)
    before_count = len(store.records)

    use_case = ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory(CONTENT_V2)),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("should-not-be-used"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
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
    stored_text = {record.chunk.content for record in store.records.values()}
    assert "ABCDEFGHIJ" in stored_text
    assert "abcdefghij" not in stored_text


def test_replace_restores_previous_row_when_mutation_did_not_start() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    original = _seed_ready(catalog, store)

    use_case = ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory(CONTENT_V2)),
        ingest_factory=lambda: IngestKnowledge(
            FailingEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("unused"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
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


def test_replace_restores_previous_row_on_validation_failure() -> None:
    """A pre-mutation validation error must not overwrite a working ready row."""
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    original = _seed_ready(catalog, store)

    use_case = ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory(CONTENT_V2)),
        # One vector short of the chunk count: `IngestKnowledge` rejects the
        # batch before its first `delete_source`, so nothing was mutated.
        ingest_factory=lambda: IngestKnowledge(
            WrongLengthEmbeddingModel(-1), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("unused"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
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


def test_replace_records_degraded_when_mutation_may_have_started() -> None:
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

    use_case = ManageUploadedDocuments(
        catalog=catalog,
        extractor=RecordingExtractor(document_factory=_document_factory(CONTENT_V2)),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("unused"),
        now=FixedClock(datetime(2026, 8, 28, 13, 0, tzinfo=UTC)),
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
