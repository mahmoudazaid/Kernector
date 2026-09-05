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
    assert projected.error_summary is None
    assert raw not in str(payload)
    assert "sk-live-secret" not in str(payload)


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


def test_pending_document_is_not_reported_as_error() -> None:
    projected = catalog_document_response(_doc(status=CatalogStatus.PENDING))

    assert projected.has_error is False
    assert projected.error_summary is None
    assert projected.status == "pending"
