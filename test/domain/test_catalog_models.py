"""Unit tests for upload payload and catalog document domain models."""

from datetime import UTC, datetime

import pytest

from domain.errors import DomainValidationError
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceReference,
    SourceType,
    UploadPayload,
)

BLANK = ["", "   ", "\n"]


def _reference(source_id: str = "doc-1") -> SourceReference:
    return SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)


def _aware_now() -> datetime:
    return datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def test_valid_upload_payload_is_accepted() -> None:
    payload = UploadPayload(file_name="guide.md", content=b"# Hello")
    assert payload.file_name == "guide.md"
    assert payload.content == b"# Hello"


@pytest.mark.parametrize("blank", BLANK)
def test_upload_payload_rejects_blank_file_name(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="file_name"):
        UploadPayload(file_name=blank, content=b"x")


def test_upload_payload_rejects_non_bytes_content() -> None:
    with pytest.raises(DomainValidationError, match="content"):
        UploadPayload(file_name="guide.md", content="not-bytes")  # type: ignore[arg-type]


def test_catalog_status_values() -> None:
    assert CatalogStatus.PENDING == "pending"
    assert CatalogStatus.READY == "ready"
    assert CatalogStatus.FAILED == "failed"
    assert CatalogStatus.DEGRADED == "degraded"


def test_valid_catalog_document_is_accepted() -> None:
    document = CatalogDocument(
        reference=_reference(),
        file_name="guide.md",
        title="Guide",
        content_format="markdown",
        status=CatalogStatus.READY,
        uploaded_at=_aware_now(),
        chunk_count=3,
        error=None,
    )
    assert document.reference.source_id == "doc-1"
    assert document.file_name == "guide.md"
    assert document.chunk_count == 3
    assert document.status is CatalogStatus.READY


@pytest.mark.parametrize("blank", BLANK)
def test_catalog_document_rejects_blank_file_name(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="file_name"):
        CatalogDocument(
            reference=_reference(),
            file_name=blank,
            title=None,
            content_format=None,
            status=CatalogStatus.PENDING,
            uploaded_at=_aware_now(),
            chunk_count=0,
            error=None,
        )


def test_catalog_document_rejects_non_reference() -> None:
    with pytest.raises(DomainValidationError, match="reference"):
        CatalogDocument(
            reference="doc-1",  # type: ignore[arg-type]
            file_name="guide.md",
            title=None,
            content_format=None,
            status=CatalogStatus.PENDING,
            uploaded_at=_aware_now(),
            chunk_count=0,
            error=None,
        )


def test_catalog_document_rejects_raw_string_status() -> None:
    with pytest.raises(DomainValidationError, match="status"):
        CatalogDocument(
            reference=_reference(),
            file_name="guide.md",
            title=None,
            content_format=None,
            status="ready",  # type: ignore[arg-type]
            uploaded_at=_aware_now(),
            chunk_count=0,
            error=None,
        )


def test_catalog_document_rejects_naive_uploaded_at() -> None:
    with pytest.raises(DomainValidationError, match="uploaded_at"):
        CatalogDocument(
            reference=_reference(),
            file_name="guide.md",
            title=None,
            content_format=None,
            status=CatalogStatus.PENDING,
            uploaded_at=datetime(2026, 8, 28, 12, 0),
            chunk_count=0,
            error=None,
        )


def test_catalog_document_rejects_negative_chunk_count() -> None:
    with pytest.raises(DomainValidationError, match="chunk_count"):
        CatalogDocument(
            reference=_reference(),
            file_name="guide.md",
            title=None,
            content_format=None,
            status=CatalogStatus.PENDING,
            uploaded_at=_aware_now(),
            chunk_count=-1,
            error=None,
        )


def test_catalog_document_rejects_bool_chunk_count() -> None:
    with pytest.raises(DomainValidationError, match="chunk_count"):
        CatalogDocument(
            reference=_reference(),
            file_name="guide.md",
            title=None,
            content_format=None,
            status=CatalogStatus.PENDING,
            uploaded_at=_aware_now(),
            chunk_count=True,  # type: ignore[arg-type]
            error=None,
        )
