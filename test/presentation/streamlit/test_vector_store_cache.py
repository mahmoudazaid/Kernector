"""Runtime behavior of Streamlit's cached vector-store seam."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    DocumentChunk,
    EmbeddedChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
    UploadPayload,
)
from domain.ports import VectorStore
from infrastructure.vectorstore.dual_write import DualWriteVectorStore
from presentation.streamlit import upload_ingest as upload_mod
from test.doubles import InMemoryLexicalIndex, InMemoryVectorStore, vector_for


@pytest.fixture
def app_module():
    import presentation.streamlit.app as app

    app._vector_store.clear()
    yield app
    app._vector_store.clear()


def test_vector_store_cache_returns_same_instance_and_builds_once(
    app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    builds: list[object] = []
    sentinel = object()

    def _fake_build(settings: object) -> object:
        builds.append(settings)
        return sentinel

    monkeypatch.setattr(app_module, "build_vector_store", _fake_build)
    monkeypatch.setattr(app_module, "_settings", lambda: object())

    first = app_module._vector_store()
    second = app_module._vector_store()

    assert first is sentinel
    assert second is sentinel
    assert len(builds) == 1


def test_cached_store_is_injected_into_chat_construction(
    app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = object()
    monkeypatch.setattr(app_module, "_vector_store", lambda: store)
    captured: dict[str, object] = {}

    def _capture_ask(
        settings: object,
        *,
        chat_model: object = None,
        vector_store: VectorStore | None = None,
        prompt_repository: object = None,
    ) -> object:
        captured["vector_store"] = vector_store
        return object()

    monkeypatch.setattr(app_module, "build_tool_augmented_ask", _capture_ask)

    # Same injection render() performs after resolving the cached store.
    app_module.build_tool_augmented_ask(
        object(),
        chat_model=object(),
        prompt_repository=object(),
        vector_store=app_module._vector_store(),
    )

    assert captured["vector_store"] is store


def test_document_mutations_forward_shared_store_to_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = DualWriteVectorStore(InMemoryVectorStore(), InMemoryLexicalIndex())
    seen: dict[str, object] = {}

    document = CatalogDocument(
        reference=SourceReference("id-1", SourceType.KNOWLEDGE_DOCUMENT),
        file_name="guide.txt",
        title=None,
        content_format="text/plain",
        status=CatalogStatus.READY,
        uploaded_at=datetime(2026, 1, 1, tzinfo=UTC),
        chunk_count=1,
        error=None,
    )

    def _create(
        settings: object,
        payload: UploadPayload,
        *,
        vector_store: VectorStore | None = None,
    ) -> CatalogDocument:
        seen["create"] = vector_store
        assert isinstance(vector_store, DualWriteVectorStore)
        vector_store.upsert(
            [
                EmbeddedChunk(
                    chunk=DocumentChunk(
                        metadata=SourceMetadata(document.reference),
                        index=0,
                        content="restart runbook unique-create-token",
                    ),
                    vector=vector_for("restart runbook unique-create-token"),
                )
            ]
        )
        return document

    def _replace(
        settings: object,
        reference: SourceReference,
        payload: UploadPayload,
        *,
        vector_store: VectorStore | None = None,
    ) -> CatalogDocument:
        seen["replace"] = vector_store
        assert vector_store is store
        vector_store.upsert(
            [
                EmbeddedChunk(
                    chunk=DocumentChunk(
                        metadata=SourceMetadata(reference),
                        index=0,
                        content="replacement unique-replace-token",
                    ),
                    vector=vector_for("replacement unique-replace-token"),
                )
            ]
        )
        return document

    def _delete(
        settings: object,
        reference: SourceReference,
        *,
        vector_store: VectorStore | None = None,
    ) -> None:
        seen["delete"] = vector_store
        assert vector_store is store
        vector_store.delete_source(reference)

    monkeypatch.setattr(upload_mod, "create_uploaded_document", _create)
    monkeypatch.setattr(upload_mod, "replace_uploaded_document", _replace)
    monkeypatch.setattr(upload_mod, "delete_uploaded_document", _delete)

    created = upload_mod.create_new_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        vector_store=store,
    )
    assert created.ok is True
    assert seen["create"] is store
    assert store.lexical.search("unique-create-token", 1)[0].chunk.source_id == "id-1"

    replaced = upload_mod.replace_existing_document(
        object(),
        reference=document.reference,
        filename="guide.txt",
        content=b"hello",
        vector_store=store,
    )
    assert replaced.ok is True
    assert seen["replace"] is store
    assert store.lexical.search("unique-replace-token", 1)[0].chunk.source_id == "id-1"

    deleted = upload_mod.delete_existing_document(
        object(),
        reference=document.reference,
        vector_store=store,
    )
    assert deleted.ok is True
    assert seen["delete"] is store
    assert all(
        hit.chunk.source_id != "id-1"
        for hit in store.lexical.search("unique-replace-token", 5)
    )
