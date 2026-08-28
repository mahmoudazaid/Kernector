"""Offline proof: create/replace/delete/restart through composition + Chroma."""

from __future__ import annotations

from pathlib import Path

import pytest

from composition import container as composition_container
from domain.knowledge import CatalogStatus, UploadPayload
from infrastructure.catalog.json_catalog import JsonDocumentCatalog
from infrastructure.config import load_settings
from infrastructure.vectorstore.chroma import ChromaVectorStore
from test.doubles import StubEmbeddingModel, vector_for

COLLECTION = "kernector_uploads"
CHUNK_SIZE = 10
CHUNK_OVERLAP = 2
CONTENT = "abcdefghijklmnopqrstuvwxyz"
CONTENT_V2 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PROBE = vector_for("probe")


def _source_ids(store: ChromaVectorStore) -> set[str]:
    return {
        scored.chunk.reference.source_id
        for scored in store.search(PROBE, 1000)
    }


@pytest.fixture
def manage_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("CHROMA_PERSIST_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION", COLLECTION)
    monkeypatch.setenv(
        "DOCUMENT_CATALOG_PATH", str(tmp_path / "catalog" / "uploads.json")
    )
    monkeypatch.setenv("CHUNK_SIZE", str(CHUNK_SIZE))
    monkeypatch.setenv("CHUNK_OVERLAP", str(CHUNK_OVERLAP))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )
    return load_settings()


def test_create_same_filename_replace_delete_and_restart(
    manage_settings,
) -> None:
    first = composition_container.create_uploaded_document(
        manage_settings,
        UploadPayload(file_name="guide.md", content=CONTENT.encode()),
    )
    second = composition_container.create_uploaded_document(
        manage_settings,
        UploadPayload(file_name="guide.md", content=b"# other\n" + CONTENT.encode()),
    )

    assert first.reference.source_id != second.reference.source_id
    assert first.file_name == second.file_name == "guide.md"
    assert first.status is CatalogStatus.READY
    assert second.status is CatalogStatus.READY

    listed = composition_container.list_uploaded_documents(manage_settings)
    assert {row.reference.source_id for row in listed} == {
        first.reference.source_id,
        second.reference.source_id,
    }

    replaced = composition_container.replace_uploaded_document(
        manage_settings,
        first.reference,
        UploadPayload(file_name="guide-v2.md", content=CONTENT_V2.encode()),
    )
    assert replaced.reference == first.reference
    assert replaced.file_name == "guide-v2.md"

    store = ChromaVectorStore(manage_settings.chroma)
    assert first.reference.source_id in _source_ids(store)
    assert second.reference.source_id in _source_ids(store)
    contents = {
        scored.chunk.content
        for scored in store.search(PROBE, 1000)
        if scored.chunk.reference.source_id == first.reference.source_id
    }
    assert any(text.startswith("ABCDEFGHIJ") for text in contents)
    assert not any(text.startswith("abcdefghij") for text in contents)

    composition_container.delete_uploaded_document(
        manage_settings, second.reference
    )
    assert second.reference.source_id not in _source_ids(
        ChromaVectorStore(manage_settings.chroma)
    )
    assert second.reference.source_id not in {
        row.reference.source_id
        for row in composition_container.list_uploaded_documents(manage_settings)
    }

    # Sequential process restart: new adapter instances, same durable paths.
    reopened_catalog = JsonDocumentCatalog(manage_settings.document_catalog.path)
    reopened_ids = {row.reference.source_id for row in reopened_catalog.all()}
    assert first.reference.source_id in reopened_ids
    assert second.reference.source_id not in reopened_ids
    assert first.reference.source_id in _source_ids(
        ChromaVectorStore(manage_settings.chroma)
    )
