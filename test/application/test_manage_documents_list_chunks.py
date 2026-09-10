"""ManageUploadedDocuments.list_document_chunks: catalog gate then vector list."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from application.manage_documents import (
    ManageUploadedDocuments,
    UnknownDocumentError,
)
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    DocumentChunk,
    EmbeddedChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from test.document_doubles import InMemoryDocumentCatalog
from test.doubles import InMemoryVectorStore, vector_for

_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
_NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _reference(
    source_id: str = "doc-1",
    source_type: str = SourceType.KNOWLEDGE_DOCUMENT,
) -> SourceReference:
    return SourceReference(source_id, source_type)


def _catalog_row(reference: SourceReference) -> CatalogDocument:
    return CatalogDocument(
        reference=reference,
        file_name="doc.txt",
        title="Doc",
        content_format="text/plain",
        status=CatalogStatus.READY,
        uploaded_at=_NOW,
        chunk_count=0,
        error=None,
    )


def _chunk(
    reference: SourceReference,
    *,
    index: int,
    content: str,
) -> DocumentChunk:
    return DocumentChunk(
        metadata=SourceMetadata(reference, title="Doc"),
        index=index,
        content=content,
    )


def _use_case(
    catalog: InMemoryDocumentCatalog,
    store: InMemoryVectorStore,
    *,
    factory_calls: list[object] | None = None,
) -> ManageUploadedDocuments:
    def factory() -> InMemoryVectorStore:
        if factory_calls is not None:
            factory_calls.append(object())
        return store

    return ManageUploadedDocuments(
        catalog=catalog,
        extractor=object(),  # type: ignore[arg-type]
        ingest_factory=lambda: object(),  # type: ignore[arg-type, return-value]
        vector_store_factory=factory,
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    )


def test_list_document_chunks_unknown_never_opens_vector_store() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    factory_calls: list[object] = []
    use_case = _use_case(catalog, store, factory_calls=factory_calls)

    with pytest.raises(UnknownDocumentError) as raised:
        use_case.list_document_chunks(_reference("missing"))

    assert raised.value.source_id == "missing"
    assert raised.value.source_type == SourceType.KNOWLEDGE_DOCUMENT
    assert factory_calls == []


def test_list_document_chunks_known_empty_returns_empty() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    reference = _reference()
    catalog.upsert(_catalog_row(reference))
    use_case = _use_case(catalog, store)

    assert use_case.list_document_chunks(reference) == ()


def test_list_document_chunks_returns_ordered_chunks() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    reference = _reference()
    catalog.upsert(_catalog_row(reference))
    store.upsert(
        [
            EmbeddedChunk(
                chunk=_chunk(reference, index=2, content="third"),
                vector=vector_for("third"),
            ),
            EmbeddedChunk(
                chunk=_chunk(reference, index=0, content="first"),
                vector=vector_for("first"),
            ),
            EmbeddedChunk(
                chunk=_chunk(reference, index=1, content="second"),
                vector=vector_for("second"),
            ),
        ]
    )
    use_case = _use_case(catalog, store)

    listed = use_case.list_document_chunks(reference)

    assert [c.index for c in listed] == [0, 1, 2]
    assert [c.content for c in listed] == ["first", "second", "third"]


def test_list_document_chunks_isolates_same_id_under_different_types() -> None:
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    kd_ref = _reference("shared", SourceType.KNOWLEDGE_DOCUMENT)
    gd_ref = _reference("shared", SourceType.GOOGLE_DRIVE)
    catalog.upsert(_catalog_row(kd_ref))
    catalog.upsert(_catalog_row(gd_ref))
    store.upsert(
        [
            EmbeddedChunk(
                chunk=_chunk(kd_ref, index=0, content="kd"),
                vector=vector_for("kd"),
            ),
            EmbeddedChunk(
                chunk=_chunk(gd_ref, index=0, content="gd"),
                vector=vector_for("gd"),
            ),
        ]
    )
    use_case = _use_case(catalog, store)

    listed = use_case.list_document_chunks(kd_ref)

    assert [c.content for c in listed] == ["kd"]
    assert listed[0].reference.source_type == SourceType.KNOWLEDGE_DOCUMENT
