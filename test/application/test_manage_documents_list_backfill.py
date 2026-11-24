"""list() backfills missing upload/Drive descriptors without 500s (#373)."""

from __future__ import annotations

from datetime import UTC, datetime

from application.ingest_knowledge import IngestKnowledge
from application.manage_documents import ManageUploadedDocuments
from application.artifact.sync import SyncArtifactDescriptors
from domain.artifact.kinds import ArtifactKind
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.artifact.sql_index import SqlArtifactIndex
from infrastructure.connectors.document_artifact_extractor import (
    DocumentArtifactDescriptorExtractor,
)
from test.document_doubles import (
    FixedClock,
    FixedIdFactory,
    InMemoryDocumentCatalog,
    InMemoryUploadBlobStore,
    RecordingExtractor,
    upload_profile,
)
from test.doubles import InMemoryVectorStore, StubEmbeddingModel

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


class _RecordingArtifactSync:
    def __init__(self) -> None:
        self.ready: list[tuple[SourceDocument, str]] = []
        self.known: set[tuple[str, str]] = set()
        self.remove_calls = 0

    def has_descriptor(self, reference: SourceReference) -> bool:
        return (reference.source_type, reference.source_id) in self.known

    def on_ready(self, source: SourceDocument, *, revision: str) -> None:
        self.ready.append((source, revision))
        self.known.add((source.reference.source_type, source.reference.source_id))

    def on_skipped(self, reference: SourceReference) -> None:
        return None

    def on_removed(self, reference: SourceReference) -> None:
        self.remove_calls += 1
        self.known.discard((reference.source_type, reference.source_id))


def _document_factory(payload, reference: SourceReference) -> SourceDocument:  # noqa: ANN001
    return SourceDocument(
        SourceMetadata(
            reference,
            title="t",
            provider="upload",
            content_format="markdown",
        ),
        "body",
    )


def _row(
    source_id: str,
    source_type: str,
    *,
    fingerprint: str | None = "fp-1",
) -> CatalogDocument:
    return CatalogDocument(
        reference=SourceReference(source_id, source_type),
        file_name=f"{source_id}.md",
        title=source_id,
        content_format="markdown",
        status=CatalogStatus.READY,
        created_at=NOW,
        updated_at=NOW,
        chunk_count=1,
        error=None,
        revision="1",
        content_fingerprint=fingerprint,
    )


def _use_case(
    catalog: InMemoryDocumentCatalog,
    artifact_sync: object,
) -> ManageUploadedDocuments:
    store = InMemoryVectorStore()
    return ManageUploadedDocuments(
        catalog=catalog,
        blob_store=InMemoryUploadBlobStore(),
        extractor=RecordingExtractor(document_factory=_document_factory),
        ingest_factory=lambda: IngestKnowledge(
            StubEmbeddingModel(), store, chunk_size=10, chunk_overlap=2
        ),
        vector_store_factory=lambda: store,
        new_source_id=FixedIdFactory("unused"),
        now=FixedClock(NOW),
        max_upload_bytes=5 * 1024 * 1024,
        processing_profile_factory=upload_profile,
        artifact_sync=artifact_sync,  # type: ignore[arg-type]
    )


def test_list_backfills_upload_with_nonempty_placeholder_content() -> None:
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("upload-1", SourceType.KNOWLEDGE_DOCUMENT))
    sync = _RecordingArtifactSync()

    listed = _use_case(catalog, sync).list()

    assert len(listed) == 1
    assert len(sync.ready) == 1
    source, revision = sync.ready[0]
    assert source.content == "."
    assert revision == "fp-1"
    assert source.metadata.extra["content_fingerprint"] == "fp-1"


def test_list_backfills_drive_and_skips_jira_github() -> None:
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("drive-1", SourceType.GOOGLE_DRIVE))
    catalog.upsert(_row("cloud/PROJ:PROJ-1", SourceType.JIRA))
    catalog.upsert(_row("acme/repo:README.md", SourceType.GITHUB))
    sync = _RecordingArtifactSync()

    listed = _use_case(catalog, sync).list()

    assert len(listed) == 3
    assert len(sync.ready) == 1
    assert sync.ready[0][0].reference.source_type == SourceType.GOOGLE_DRIVE
    assert sync.ready[0][0].metadata.extra["drive_revision"] == "fp-1"
    assert sync.remove_calls == 0


def test_list_with_real_sync_hook_does_not_500_on_preexisting_upload(
    tmp_path,
) -> None:
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("upload-1", SourceType.KNOWLEDGE_DOCUMENT))
    index = SqlArtifactIndex(tmp_path / "catalog.sqlite", "ws_test")
    sync = SyncArtifactDescriptors(DocumentArtifactDescriptorExtractor(), index)

    listed = _use_case(catalog, sync).list()
    again = _use_case(catalog, sync).list()

    assert len(listed) == 1
    assert len(again) == 1
    stored = index.get(SourceReference("upload-1", SourceType.KNOWLEDGE_DOCUMENT))
    assert stored is not None
    assert stored.kind == ArtifactKind.DOCUMENT
