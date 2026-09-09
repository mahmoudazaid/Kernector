"""Tests for the SQLite document catalog adapter."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceReference,
    SourceType,
)
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog import _connection as connection_module
from infrastructure.catalog.sql_catalog import SqlDocumentCatalog

WAL_SAFE_VERSION = (3, 51, 3)
ROLLBACK_JOURNAL_VERSION = (3, 51, 2)


def _reference(
    source_id: str = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    source_type: str = SourceType.KNOWLEDGE_DOCUMENT,
) -> SourceReference:
    return SourceReference(source_id, source_type)


def _document(
    *,
    source_id: str = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    source_type: str = SourceType.KNOWLEDGE_DOCUMENT,
    file_name: str = "guide.md",
    title: str | None = "Guide",
    content_format: str | None = "markdown",
    status: CatalogStatus = CatalogStatus.READY,
    uploaded_at: datetime | None = None,
    chunk_count: int = 2,
    error: str | None = None,
    revision: str | None = None,
) -> CatalogDocument:
    return CatalogDocument(
        reference=_reference(source_id, source_type),
        file_name=file_name,
        title=title,
        content_format=content_format,
        status=status,
        uploaded_at=uploaded_at or datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        chunk_count=chunk_count,
        error=error,
        revision=revision,
    )


def test_missing_file_returns_empty_catalog(tmp_path: Path) -> None:
    catalog = SqlDocumentCatalog(tmp_path / "missing" / "catalog.sqlite", "ws-a")
    assert catalog.all() == ()
    assert catalog.get(_reference()) is None


def test_upsert_list_get_round_trip(tmp_path: Path) -> None:
    catalog = SqlDocumentCatalog(tmp_path / "catalog.sqlite", "ws-a")
    document = _document(
        status=CatalogStatus.DEGRADED,
        chunk_count=0,
        error="upsert failed",
        revision="42",
        uploaded_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )
    catalog.upsert(document)
    assert catalog.all() == (document,)
    assert catalog.get(document.reference) == document


def test_reopen_reads_persisted_records(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    SqlDocumentCatalog(path, "ws-a").upsert(_document())
    assert SqlDocumentCatalog(path, "ws-a").all() == (_document(),)


def test_delete_removes_record(tmp_path: Path) -> None:
    catalog = SqlDocumentCatalog(tmp_path / "catalog.sqlite", "ws-a")
    document = _document()
    catalog.upsert(document)
    catalog.delete(document.reference)
    assert catalog.all() == ()
    assert catalog.get(document.reference) is None


def test_delete_missing_is_noop(tmp_path: Path) -> None:
    catalog = SqlDocumentCatalog(tmp_path / "catalog.sqlite", "ws-a")
    catalog.delete(_reference())
    assert catalog.all() == ()


def test_upsert_replaces_existing_record(tmp_path: Path) -> None:
    catalog = SqlDocumentCatalog(tmp_path / "catalog.sqlite", "ws-a")
    catalog.upsert(_document(chunk_count=1))
    updated = _document(chunk_count=5, file_name="guide-v2.md")
    catalog.upsert(updated)
    assert catalog.all() == (updated,)


def test_opaque_source_type_round_trips(tmp_path: Path) -> None:
    catalog = SqlDocumentCatalog(tmp_path / "catalog.sqlite", "ws-a")
    document = _document(source_id="id-opaque", source_type="connector_feed")
    catalog.upsert(document)
    assert catalog.all() == (document,)


def test_optional_fields_round_trip_as_absent(tmp_path: Path) -> None:
    catalog = SqlDocumentCatalog(tmp_path / "catalog.sqlite", "ws-a")
    document = _document(title=None, content_format=None, error=None, revision=None)
    catalog.upsert(document)
    assert catalog.get(document.reference) == document


def test_workspaces_isolate_the_same_source_identity(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    workspace_a = SqlDocumentCatalog(path, "ws-a")
    workspace_b = SqlDocumentCatalog(path, "ws-b")
    document_a = _document(file_name="a.md", chunk_count=1)
    document_b = _document(file_name="b.md", chunk_count=9, title="Other")
    workspace_a.upsert(document_a)
    workspace_b.upsert(document_b)
    assert workspace_a.all() == (document_a,)
    assert workspace_b.all() == (document_b,)
    assert workspace_a.get(document_a.reference) == document_a
    assert workspace_b.get(document_b.reference) == document_b


@pytest.mark.parametrize("workspace_id", ["bad id", "ws/id", "w" * 65, "", "   "])
def test_constructor_rejects_invalid_workspace_id_before_filesystem(
    tmp_path: Path, workspace_id: str
) -> None:
    path = tmp_path / "nested" / "catalog.sqlite"
    with pytest.raises(ValueError, match="workspace_id"):
        SqlDocumentCatalog(path, workspace_id)
    assert not path.exists()
    assert not path.parent.exists()


@pytest.mark.parametrize(
    "sqlite_version",
    [WAL_SAFE_VERSION, ROLLBACK_JOURNAL_VERSION],
)
def test_concurrent_distinct_identities_are_both_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sqlite_version: tuple[int, ...]
) -> None:
    monkeypatch.setattr(sqlite3, "sqlite_version_info", sqlite_version)
    path = tmp_path / "catalog.sqlite"
    SqlDocumentCatalog(path, "ws-a")

    def write(source_id: str) -> None:
        SqlDocumentCatalog(path, "ws-a").upsert(
            _document(source_id=source_id, file_name=f"{source_id}.md")
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(write, "id-a"),
            pool.submit(write, "id-b"),
        ]
        for future in futures:
            future.result(timeout=10)

    ids = {doc.reference.source_id for doc in SqlDocumentCatalog(path, "ws-a").all()}
    assert ids == {"id-a", "id-b"}


@pytest.mark.parametrize(
    "sqlite_version",
    [WAL_SAFE_VERSION, ROLLBACK_JOURNAL_VERSION],
)
def test_concurrent_same_identity_yields_one_complete_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sqlite_version: tuple[int, ...]
) -> None:
    monkeypatch.setattr(sqlite3, "sqlite_version_info", sqlite_version)
    path = tmp_path / "catalog.sqlite"
    SqlDocumentCatalog(path, "ws-a")

    def write(file_name: str, chunk_count: int) -> None:
        SqlDocumentCatalog(path, "ws-a").upsert(
            _document(
                source_id="id-same",
                file_name=file_name,
                chunk_count=chunk_count,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(write, "a.md", 1),
            pool.submit(write, "b.md", 9),
        ]
        for future in futures:
            future.result(timeout=10)

    rows = SqlDocumentCatalog(path, "ws-a").all()
    assert len(rows) == 1
    assert rows[0].reference == _reference("id-same")
    assert rows[0].file_name in {"a.md", "b.md"}
    assert rows[0].chunk_count in {1, 9}


def test_failed_write_preserves_prior_readable_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "catalog.sqlite"
    catalog = SqlDocumentCatalog(path, "ws-a")
    document = _document()
    catalog.upsert(document)
    fail_writes = True
    real_connect = connection_module.connect

    class _FailingConnection:
        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner

        def execute(self, sql: str, parameters: object = ()) -> sqlite3.Cursor:
            if fail_writes and "INSERT" in sql.upper():
                raise sqlite3.OperationalError("injected write failure")
            return self._inner.execute(sql, parameters)

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    def connect_and_fail(*args: object, **kwargs: object) -> object:
        return _FailingConnection(real_connect(*args, **kwargs))

    monkeypatch.setattr(connection_module, "connect", connect_and_fail)
    with pytest.raises(CatalogError) as raised:
        catalog.upsert(_document(file_name="other.md", chunk_count=9))
    assert isinstance(raised.value.__cause__, sqlite3.Error)

    fail_writes = False
    assert catalog.all() == (document,)
    assert catalog.get(document.reference) == document
