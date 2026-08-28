"""Composition entry points for uploaded-document management."""

from __future__ import annotations

from pathlib import Path

import pytest

from application.manage_documents import PartialDeleteFailure, UnknownDocumentError
from composition import container as composition_container
from composition.errors import DocumentOperationError, DocumentUploadError
from domain.knowledge import (
    CatalogStatus,
    SourceReference,
    SourceType,
    UploadPayload,
)
from infrastructure.config import Settings, load_settings


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("CHROMA_PERSIST_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION", "kernector_test")
    monkeypatch.setenv("DOCUMENT_CATALOG_PATH", str(tmp_path / "catalog" / "uploads.json"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    return load_settings()


def test_build_document_catalog_uses_settings_path(settings: Settings) -> None:
    catalog = composition_container.build_document_catalog(settings)
    assert catalog.all() == ()
    assert settings.document_catalog.path == settings.document_catalog.path


def test_list_create_replace_delete_round_trip(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test.doubles import StubEmbeddingModel

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )

    created = composition_container.create_uploaded_document(
        settings,
        UploadPayload(file_name="guide.md", content=b"# Hello world content\n" * 20),
    )
    assert created.status is CatalogStatus.READY
    assert created.reference.source_type is SourceType.KNOWLEDGE_DOCUMENT

    listed = composition_container.list_uploaded_documents(settings)
    assert len(listed) == 1
    assert listed[0].reference == created.reference

    replaced = composition_container.replace_uploaded_document(
        settings,
        created.reference,
        UploadPayload(file_name="guide-v2.md", content=b"# Replacement text\n" * 20),
    )
    assert replaced.reference == created.reference
    assert replaced.file_name == "guide-v2.md"

    composition_container.delete_uploaded_document(settings, created.reference)
    assert composition_container.list_uploaded_documents(settings) == ()


def test_replace_unknown_becomes_document_operation_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test.doubles import StubEmbeddingModel

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )
    missing = SourceReference("missing", SourceType.KNOWLEDGE_DOCUMENT)
    with pytest.raises(DocumentOperationError) as raised:
        composition_container.replace_uploaded_document(
            settings,
            missing,
            UploadPayload(file_name="x.md", content=b"# x\n"),
        )
    assert isinstance(raised.value.__cause__, UnknownDocumentError)


def test_create_extraction_failure_becomes_document_upload_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test.doubles import StubEmbeddingModel

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )
    with pytest.raises(DocumentUploadError):
        composition_container.create_uploaded_document(
            settings,
            UploadPayload(file_name="notes.docx", content=b"x"),
        )


def test_partial_delete_is_translated(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test.doubles import StubEmbeddingModel

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )
    created = composition_container.create_uploaded_document(
        settings,
        UploadPayload(file_name="guide.md", content=b"# Hello world content\n" * 20),
    )

    class ExplodingCatalog:
        def all(self):
            return ()

        def get(self, reference):
            return created

        def upsert(self, document):
            return None

        def delete(self, reference):
            raise RuntimeError("disk full")

    monkeypatch.setattr(
        composition_container,
        "build_document_catalog",
        lambda _settings: ExplodingCatalog(),
    )
    with pytest.raises(DocumentOperationError) as raised:
        composition_container.delete_uploaded_document(settings, created.reference)
    assert isinstance(raised.value.__cause__, PartialDeleteFailure)
