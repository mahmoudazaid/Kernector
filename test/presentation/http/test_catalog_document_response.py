"""Wire projection for uploaded catalog documents."""

from datetime import UTC, datetime

from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceReference,
    SourceType,
)
from presentation.http.schemas import catalog_document_response


def _doc(
    *,
    status: CatalogStatus = CatalogStatus.READY,
    error: str | None = None,
) -> CatalogDocument:
    return CatalogDocument(
        reference=SourceReference(
            source_id="0f0fabc",
            source_type=SourceType.KNOWLEDGE_DOCUMENT,
        ),
        file_name="spec.md",
        title="Spec",
        content_format="markdown",
        status=status,
        uploaded_at=datetime(2026, 9, 5, 9, 12, 44, tzinfo=UTC),
        chunk_count=7,
        error=error,
    )


def test_ready_document_projection_omits_error_text() -> None:
    raw = "OpenRouter 401: invalid key sk-live-secret"
    projected = catalog_document_response(_doc(error=raw))
    payload = projected.model_dump()

    assert projected.source_id == "0f0fabc"
    assert projected.status == "ready"
    assert projected.chunk_count == 7
    assert projected.has_error is False
    assert projected.has_stored_content is True
    assert projected.error_summary is None
    assert raw not in str(payload)
    assert "sk-live-secret" not in str(payload)


def test_missing_blob_ready_row_is_not_degraded() -> None:
    from application.manage_documents import MISSING_UPLOAD_BLOB_ERROR

    projected = catalog_document_response(
        _doc(status=CatalogStatus.READY, error=MISSING_UPLOAD_BLOB_ERROR)
    )

    assert projected.status == "ready"
    assert projected.has_error is True
    assert projected.has_stored_content is False
    assert projected.error_summary is not None
    assert "preview" in projected.error_summary.lower()
    assert MISSING_UPLOAD_BLOB_ERROR not in (projected.error_summary or "")


def test_failed_document_uses_fixed_summary_not_adapter_text() -> None:
    raw = "extractor failed at /var/tmp/upload.pdf"
    projected = catalog_document_response(
        _doc(status=CatalogStatus.FAILED, error=raw)
    )
    payload = projected.model_dump()

    assert projected.has_error is True
    assert projected.error_summary == (
        "Ingestion failed for this document. Delete it and upload again."
    )
    assert raw not in str(payload)
    assert "/var/tmp" not in str(payload)


def test_failed_drive_document_uses_sync_guidance() -> None:
    projected = catalog_document_response(
        CatalogDocument(
            reference=SourceReference(
                source_id="file-9",
                source_type=SourceType.GOOGLE_DRIVE,
            ),
            file_name="guide.md",
            title=None,
            content_format=None,
            status=CatalogStatus.FAILED,
            uploaded_at=datetime(2026, 9, 5, 9, 12, 44, tzinfo=UTC),
            chunk_count=0,
            error="ConnectorError",
            revision="8",
        )
    )

    assert projected.has_error is True
    assert projected.error_summary == (
        "This Google Drive file could not be indexed. Sync again or remove it in Browse."
    )


def test_degraded_drive_document_uses_sync_guidance() -> None:
    projected = catalog_document_response(
        CatalogDocument(
            reference=SourceReference(
                source_id="file-9",
                source_type=SourceType.GOOGLE_DRIVE,
            ),
            file_name="guide.md",
            title=None,
            content_format=None,
            status=CatalogStatus.DEGRADED,
            uploaded_at=datetime(2026, 9, 5, 9, 12, 44, tzinfo=UTC),
            chunk_count=2,
            error="partial",
            revision="8",
        )
    )

    assert projected.has_error is True
    assert projected.error_summary == (
        "Indexing did not finish cleanly. Sync again or remove it in Browse."
    )


def test_pending_document_is_not_reported_as_error() -> None:
    projected = catalog_document_response(_doc(status=CatalogStatus.PENDING))

    assert projected.has_error is False
    assert projected.error_summary is None
    assert projected.status == "pending"
