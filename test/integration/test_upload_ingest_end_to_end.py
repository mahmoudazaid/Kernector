"""Offline vertical proof: upload extract → composition ingest → real Chroma.

Patches ``load_dotenv`` before env overrides so a local ``.env`` cannot redirect
writes. Patches ``build_embedding_model`` (not ``build_ingest_knowledge``) so
chunking, ``IngestKnowledge``, and ``ChromaVectorStore`` stay on the path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from composition import ingest_uploaded_document
from composition import container as composition_container
from infrastructure.config import load_settings
from infrastructure.vectorstore.chroma import ChromaVectorStore
from test.doubles import StubEmbeddingModel, vector_for

COLLECTION = "kernector_knowledge"
CHUNK_SIZE = 10
CHUNK_OVERLAP = 2
# 26 characters. Step 8 → windows [0:10], [8:18], [16:26] = 3 chunks.
CONTENT = "abcdefghijklmnopqrstuvwxyz"
PROBE = vector_for("probe")


def _identities(store: ChromaVectorStore) -> list[tuple[str, int]]:
    return sorted(
        (scored.chunk.reference.source_id, scored.chunk.index)
        for scored in store.search(PROBE, 1000)
    )


@pytest.fixture
def upload_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    target = tmp_path / "chroma"
    monkeypatch.setenv("CHROMA_PERSIST_PATH", str(target))
    monkeypatch.setenv("CHROMA_COLLECTION", COLLECTION)
    monkeypatch.setenv("CHUNK_SIZE", str(CHUNK_SIZE))
    monkeypatch.setenv("CHUNK_OVERLAP", str(CHUNK_OVERLAP))
    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )
    settings = load_settings()
    assert settings.chroma.persist_path == target
    assert settings.chunking.chunk_size == CHUNK_SIZE
    assert settings.chunking.chunk_overlap == CHUNK_OVERLAP
    return settings


def test_uploaded_document_reaches_temporary_chroma(
    upload_settings,
    tmp_path: Path,
) -> None:
    path = tmp_path / "guide.txt"
    path.write_text(CONTENT, encoding="utf-8")

    response = ingest_uploaded_document(
        upload_settings, path, source_id="upload-001"
    )

    assert response.accepted_ids == ("upload-001",)
    # Hand-sliced against size 10 / overlap 2 — not read back from the use case.
    assert response.chunk_count == 3

    store = ChromaVectorStore(upload_settings.chroma)
    assert _identities(store) == [
        ("upload-001", 0),
        ("upload-001", 1),
        ("upload-001", 2),
    ]


def test_matching_filenames_with_distinct_source_ids_both_persist(
    upload_settings,
    tmp_path: Path,
) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "guide.md"
    second = second_dir / "guide.md"
    first.write_text("# first\n\n" + CONTENT, encoding="utf-8")
    second.write_text("# second\n\nabc", encoding="utf-8")

    first_response = ingest_uploaded_document(
        upload_settings, first, source_id="guide-a"
    )
    second_response = ingest_uploaded_document(
        upload_settings, second, source_id="guide-b"
    )

    assert "guide-a" in first_response.accepted_ids
    assert "guide-b" in second_response.accepted_ids

    store = ChromaVectorStore(upload_settings.chroma)
    source_ids = {source_id for source_id, _index in _identities(store)}
    assert source_ids == {"guide-a", "guide-b"}
