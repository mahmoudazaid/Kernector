"""Unit tests for upload payload and catalog document domain models."""

from datetime import UTC, datetime

import pytest

from domain.errors import DomainValidationError
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceMetadata,
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
        created_at=_aware_now(),
        updated_at=_aware_now(),
        chunk_count=3,
        error=None,
    )
    assert document.reference.source_id == "doc-1"
    assert document.file_name == "guide.md"
    assert document.chunk_count == 3
    assert document.status is CatalogStatus.READY
    assert document.created_at == _aware_now()
    assert document.updated_at == _aware_now()


@pytest.mark.parametrize("blank", BLANK)
def test_catalog_document_rejects_blank_file_name(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="file_name"):
        CatalogDocument(
            reference=_reference(),
            file_name=blank,
            title=None,
            content_format=None,
            status=CatalogStatus.PENDING,
            created_at=_aware_now(),
            updated_at=_aware_now(),
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
            created_at=_aware_now(),
            updated_at=_aware_now(),
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
            created_at=_aware_now(),
            updated_at=_aware_now(),
            chunk_count=0,
            error=None,
        )


def test_catalog_document_rejects_naive_created_at() -> None:
    with pytest.raises(DomainValidationError, match="created_at"):
        CatalogDocument(
            reference=_reference(),
            file_name="guide.md",
            title=None,
            content_format=None,
            status=CatalogStatus.PENDING,
            created_at=datetime(2026, 8, 28, 12, 0),
            updated_at=_aware_now(),
            chunk_count=0,
            error=None,
        )


def test_catalog_document_rejects_naive_updated_at() -> None:
    with pytest.raises(DomainValidationError, match="updated_at"):
        CatalogDocument(
            reference=_reference(),
            file_name="guide.md",
            title=None,
            content_format=None,
            status=CatalogStatus.PENDING,
            created_at=_aware_now(),
            updated_at=datetime(2026, 8, 28, 12, 0),
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
            created_at=_aware_now(),
            updated_at=_aware_now(),
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
            created_at=_aware_now(),
            updated_at=_aware_now(),
            chunk_count=True,  # type: ignore[arg-type]
            error=None,
        )


def test_catalog_document_revision_defaults_to_none() -> None:
    document = CatalogDocument(
        reference=_reference(),
        file_name="guide.md",
        title=None,
        content_format=None,
        status=CatalogStatus.READY,
        created_at=_aware_now(),
        updated_at=_aware_now(),
        chunk_count=1,
        error=None,
    )
    assert document.revision is None


def test_catalog_document_accepts_explicit_revision() -> None:
    document = CatalogDocument(
        reference=_reference(),
        file_name="guide.md",
        title=None,
        content_format=None,
        status=CatalogStatus.READY,
        created_at=_aware_now(),
        updated_at=_aware_now(),
        chunk_count=1,
        error=None,
        revision="42",
    )
    assert document.revision == "42"


def test_catalog_document_rejects_non_string_revision() -> None:
    with pytest.raises(DomainValidationError, match="revision"):
        CatalogDocument(
            reference=_reference(),
            file_name="guide.md",
            title=None,
            content_format=None,
            status=CatalogStatus.READY,
            created_at=_aware_now(),
            updated_at=_aware_now(),
            chunk_count=1,
            error=None,
            revision=42,  # type: ignore[arg-type]
        )


def test_catalog_document_connector_id_defaults_to_none() -> None:
    document = CatalogDocument(
        reference=_reference(),
        file_name="guide.md",
        title=None,
        content_format=None,
        status=CatalogStatus.READY,
        created_at=_aware_now(),
        updated_at=_aware_now(),
        chunk_count=1,
        error=None,
    )
    assert document.connector_id is None


def test_catalog_document_rejects_blank_connector_id() -> None:
    with pytest.raises(DomainValidationError, match="connector_id"):
        CatalogDocument(
            reference=_reference(),
            file_name="guide.md",
            title=None,
            content_format=None,
            status=CatalogStatus.READY,
            created_at=_aware_now(),
            updated_at=_aware_now(),
            chunk_count=1,
            error=None,
            connector_id="   ",
        )


def test_source_metadata_timestamps_default_to_none() -> None:
    metadata = SourceMetadata(reference=_reference())
    assert metadata.created_at is None
    assert metadata.updated_at is None


def test_source_metadata_accepts_timezone_aware_timestamps() -> None:
    metadata = SourceMetadata(
        reference=_reference(),
        created_at=_aware_now(),
        updated_at=_aware_now(),
    )
    assert metadata.created_at == _aware_now()
    assert metadata.updated_at == _aware_now()


def test_source_metadata_rejects_naive_created_at() -> None:
    with pytest.raises(DomainValidationError, match="created_at"):
        SourceMetadata(
            reference=_reference(),
            created_at=datetime(2026, 8, 28, 12, 0),
        )


def test_source_metadata_rejects_naive_updated_at() -> None:
    with pytest.raises(DomainValidationError, match="updated_at"):
        SourceMetadata(
            reference=_reference(),
            updated_at=datetime(2026, 8, 28, 12, 0),
        )
