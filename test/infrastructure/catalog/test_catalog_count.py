"""Catalog count filters for the SQL adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from domain.knowledge import CatalogDocument, CatalogStatus, SourceReference, SourceType
from infrastructure.catalog.sql_catalog import SqlDocumentCatalog


def _upload(source_id: str, *, status: CatalogStatus = CatalogStatus.READY) -> CatalogDocument:
    return CatalogDocument(
        reference=SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT),
        file_name="guide.md",
        title="Guide",
        content_format="markdown",
        status=status,
        uploaded_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        chunk_count=2,
        error=None,
    )


def test_count_filters_source_type_and_status(tmp_path: Path) -> None:
    catalog = SqlDocumentCatalog(tmp_path / "catalog.sqlite", "ws-a")
    other = SqlDocumentCatalog(tmp_path / "catalog.sqlite", "ws-b")
    other.upsert(_upload("cccccccc-bbbb-cccc-dddd-eeeeeeeeeeee"))
    catalog.upsert(_upload("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))
    catalog.upsert(
        _upload("bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee", status=CatalogStatus.FAILED)
    )
    catalog.upsert(
        CatalogDocument(
            reference=SourceReference("drive-ready", SourceType.GOOGLE_DRIVE),
            file_name="drive.md",
            title="Drive",
            content_format="markdown",
            status=CatalogStatus.READY,
            uploaded_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
            chunk_count=1,
            error=None,
        )
    )

    assert catalog.count() == 3
    assert catalog.count(source_type=SourceType.GOOGLE_DRIVE) == 1
    assert (
        catalog.count(source_type=SourceType.GOOGLE_DRIVE, status=CatalogStatus.READY)
        == 1
    )
    assert catalog.count(status=CatalogStatus.FAILED) == 1
    assert catalog.count(status=CatalogStatus.READY) == 2
    assert other.count() == 1
