"""Composition wrapper for JSON to SQL catalog migration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from application.errors import ConfigurationError
from composition import container as composition_container
from composition.errors import DocumentOperationError
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceReference,
    SourceType,
)
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.json_catalog import JsonDocumentCatalog
from infrastructure.catalog.sql_catalog import SqlDocumentCatalog
from infrastructure.config import load_settings


def _document() -> CatalogDocument:
    return CatalogDocument(
        reference=SourceReference("id-1", SourceType.KNOWLEDGE_DOCUMENT),
        file_name="guide.md",
        title="Guide",
        content_format="markdown",
        status=CatalogStatus.READY,
        uploaded_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        chunk_count=2,
        error=None,
        revision="1",
    )


def test_wrapper_requires_sql_backend_before_opening_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("DOCUMENT_CATALOG_BACKEND", "json")
    monkeypatch.setenv("DOCUMENT_CATALOG_PATH", str(tmp_path / "uploads.json"))
    monkeypatch.setenv(
        "DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "missing" / "catalog.sqlite")
    )
    settings = load_settings()
    with pytest.raises(ConfigurationError, match="DOCUMENT_CATALOG_BACKEND"):
        composition_container.migrate_document_catalog(settings)
    assert not (tmp_path / "missing" / "catalog.sqlite").exists()


def test_wrapper_imports_json_into_configured_sql_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    json_path = tmp_path / "uploads.json"
    sql_path = tmp_path / "catalog.sqlite"
    JsonDocumentCatalog(json_path).upsert(_document())
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("DOCUMENT_CATALOG_BACKEND", "sql")
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "ws-a")
    monkeypatch.setenv("DOCUMENT_CATALOG_PATH", str(json_path))
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", str(sql_path))
    settings = load_settings()

    composition_container.migrate_document_catalog(settings)

    assert SqlDocumentCatalog(sql_path, "ws-a").all() == (_document(),)


def test_wrapper_maps_catalog_error_to_document_operation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("DOCUMENT_CATALOG_BACKEND", "sql")
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "ws-a")
    monkeypatch.setenv("DOCUMENT_CATALOG_PATH", str(tmp_path / "uploads.json"))
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "catalog.sqlite"))
    settings = load_settings()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise CatalogError("import failed")

    monkeypatch.setattr(
        composition_container, "_migrate_json_catalog_to_sql", _boom
    )
    with pytest.raises(DocumentOperationError, match="import failed"):
        composition_container.migrate_document_catalog(settings)
