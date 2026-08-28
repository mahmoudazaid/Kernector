"""Tests for the JSON document catalog adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceReference,
    SourceType,
)
from infrastructure.catalog.json_catalog import (
    CatalogParseError,
    CatalogValidationError,
    JsonDocumentCatalog,
)


def _reference(source_id: str = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee") -> SourceReference:
    return SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)


def _document(
    *,
    source_id: str = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    file_name: str = "guide.md",
    status: CatalogStatus = CatalogStatus.READY,
    chunk_count: int = 2,
) -> CatalogDocument:
    return CatalogDocument(
        reference=_reference(source_id),
        file_name=file_name,
        title="Guide",
        content_format="markdown",
        status=status,
        uploaded_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        chunk_count=chunk_count,
        error=None,
    )


def test_missing_file_returns_empty_catalog(tmp_path: Path) -> None:
    catalog = JsonDocumentCatalog(tmp_path / "missing" / "uploads.json")
    assert catalog.all() == ()
    assert catalog.get(_reference()) is None


def test_upsert_list_get_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "uploads.json"
    catalog = JsonDocumentCatalog(path)
    document = _document()
    catalog.upsert(document)
    assert catalog.all() == (document,)
    assert catalog.get(document.reference) == document


def test_reopen_reads_persisted_records(tmp_path: Path) -> None:
    path = tmp_path / "uploads.json"
    first = JsonDocumentCatalog(path)
    document = _document()
    first.upsert(document)
    second = JsonDocumentCatalog(path)
    assert second.all() == (document,)


def test_delete_removes_record(tmp_path: Path) -> None:
    path = tmp_path / "uploads.json"
    catalog = JsonDocumentCatalog(path)
    document = _document()
    catalog.upsert(document)
    catalog.delete(document.reference)
    assert catalog.all() == ()
    assert catalog.get(document.reference) is None


def test_delete_missing_is_noop(tmp_path: Path) -> None:
    catalog = JsonDocumentCatalog(tmp_path / "uploads.json")
    catalog.delete(_reference())
    assert catalog.all() == ()


def test_upsert_replaces_existing_record(tmp_path: Path) -> None:
    path = tmp_path / "uploads.json"
    catalog = JsonDocumentCatalog(path)
    catalog.upsert(_document(chunk_count=1))
    updated = _document(chunk_count=5, file_name="guide-v2.md")
    catalog.upsert(updated)
    assert catalog.all() == (updated,)


def test_corrupt_json_raises_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "uploads.json"
    path.write_text("{not-json", encoding="utf-8")
    catalog = JsonDocumentCatalog(path)
    with pytest.raises(CatalogParseError):
        catalog.all()


def test_invalid_payload_raises_validation_error(tmp_path: Path) -> None:
    path = tmp_path / "uploads.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    catalog = JsonDocumentCatalog(path)
    with pytest.raises(CatalogValidationError):
        catalog.all()


def test_every_read_reloads_disk_state(tmp_path: Path) -> None:
    path = tmp_path / "uploads.json"
    catalog = JsonDocumentCatalog(path)
    catalog.upsert(_document(source_id="id-1", file_name="a.md"))
    # External write simulating another writer finishing before our next read.
    other = JsonDocumentCatalog(path)
    other.upsert(_document(source_id="id-2", file_name="b.md"))
    ids = {doc.reference.source_id for doc in catalog.all()}
    assert ids == {"id-1", "id-2"}


def test_config_loading_creates_no_parent_until_write(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "uploads.json"
    catalog = JsonDocumentCatalog(path)
    assert not path.parent.exists()
    catalog.upsert(_document())
    assert path.is_file()


def test_same_process_lost_update_is_prevented(tmp_path: Path) -> None:
    """Two adapters sharing a path must not lose concurrent upserts."""
    import threading

    path = tmp_path / "uploads.json"
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def writer(source_id: str) -> None:
        try:
            catalog = JsonDocumentCatalog(path)
            barrier.wait(timeout=5)
            catalog.upsert(_document(source_id=source_id, file_name=f"{source_id}.md"))
        except BaseException as error:  # noqa: BLE001 — collect for assertion
            errors.append(error)

    threads = [
        threading.Thread(target=writer, args=("id-a",)),
        threading.Thread(target=writer, args=("id-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert errors == []
    final = JsonDocumentCatalog(path)
    ids = {doc.reference.source_id for doc in final.all()}
    assert ids == {"id-a", "id-b"}
