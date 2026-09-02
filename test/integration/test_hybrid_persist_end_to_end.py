"""Persisted Chroma + hybrid BM25 hydrate coverage for product retrieve."""

from pathlib import Path

import pytest

from application.contracts import IngestRequest, RetrieveRequest
from application.ingest_knowledge import IngestKnowledge
from application.retrieve_knowledge import RetrieveKnowledge
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.config import ChromaSettings, RetrievalSettings
from infrastructure.lexical.bm25 import Bm25LexicalIndex
from infrastructure.vectorstore.chroma import ChromaVectorStore
from infrastructure.vectorstore.dual_write import DualWriteVectorStore
from test.doubles import StubEmbeddingModel

COLLECTION = "kernector_hybrid_persist"
CHUNK_SIZE = 200
CHUNK_OVERLAP = 0


def _chroma(path: Path) -> ChromaSettings:
    return ChromaSettings(persist_path=path, collection=COLLECTION)


def _document(
    source_id: str,
    content: str,
    *,
    extra: dict[str, str] | None = None,
) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT),
            extra=extra or {},
        ),
        content,
    )


def _hybrid_store(path: Path) -> DualWriteVectorStore:
    chroma = ChromaVectorStore(_chroma(path))
    lexical = Bm25LexicalIndex()
    lexical.upsert(chroma.list_embedded_chunks())
    return DualWriteVectorStore(chroma, lexical)


def test_hybrid_hydrates_bm25_from_persisted_chroma_and_finds_exact_token(
    tmp_path: Path,
) -> None:
    persist = tmp_path / "chroma"
    embedding = StubEmbeddingModel()
    writer = ChromaVectorStore(_chroma(persist))
    IngestKnowledge(
        embedding, writer, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    ).execute(
        IngestRequest(
            documents=[
                _document(
                    "err-doc",
                    "Error ERR-4021 means the API key is missing from config.",
                ),
                _document("other", "Blue-green rollout of the payment service."),
                _document("third", "Capacity planning for the next quarter."),
            ]
        )
    )

    # New process-equivalent: rebuild hybrid from disk.
    store = _hybrid_store(persist)
    retrieve = RetrieveKnowledge(
        embedding,
        store,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=store.lexical,
        hybrid_alpha=1.0,
    )

    response = retrieve.execute(
        RetrieveRequest(query="ERR-4021", retrieval_limit=2)
    )

    assert response.hits[0].chunk.source_id == "err-doc"


def test_hybrid_hydrate_empty_persisted_collection_returns_empty(
    tmp_path: Path,
) -> None:
    store = _hybrid_store(tmp_path / "empty")
    retrieve = RetrieveKnowledge(
        StubEmbeddingModel(),
        store,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=store.lexical,
        hybrid_alpha=0.5,
    )

    assert (
        retrieve.execute(RetrieveRequest(query="anything", retrieval_limit=5)).hits
        == ()
    )


def test_hybrid_persisted_metadata_filters_still_apply(tmp_path: Path) -> None:
    persist = tmp_path / "chroma"
    embedding = StubEmbeddingModel()
    writer = ChromaVectorStore(_chroma(persist))
    IngestKnowledge(
        embedding, writer, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    ).execute(
        IngestRequest(
            documents=[
                _document(
                    "runbook",
                    "ERR-4021 recovery steps for operators",
                    extra={"doc_type": "runbook"},
                ),
                _document(
                    "policy",
                    "ERR-4021 policy note about keys",
                    extra={"doc_type": "policy"},
                ),
                _document("filler", "Unrelated capacity notes here"),
            ]
        )
    )

    store = _hybrid_store(persist)
    retrieve = RetrieveKnowledge(
        embedding,
        store,
        max_input_length=10_000,
        hybrid_enabled=True,
        lexical_index=store.lexical,
        hybrid_alpha=1.0,
    )

    response = retrieve.execute(
        RetrieveRequest(
            query="ERR-4021",
            retrieval_limit=5,
            metadata_filters={"doc_type": "runbook"},
        )
    )

    assert [hit.chunk.source_id for hit in response.hits] == ["runbook"]


def test_vector_only_build_does_not_hydrate_lexical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from composition.container import build_vector_store
    from infrastructure.config import load_settings

    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("CHROMA_PERSIST_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION", COLLECTION)
    monkeypatch.setenv("HYBRID_SEARCH_ENABLED", "false")
    settings = load_settings()
    assert settings.retrieval.hybrid_enabled is False

    hydrate_calls: list[object] = []

    def _boom(self):  # type: ignore[no-untyped-def]
        hydrate_calls.append(self)
        raise AssertionError("vector-only must not hydrate BM25")

    monkeypatch.setattr(ChromaVectorStore, "list_embedded_chunks", _boom)

    store = build_vector_store(settings)

    assert isinstance(store, ChromaVectorStore)
    assert hydrate_calls == []
    # Silence unused import warning for RetrievalSettings in type checkers
    assert isinstance(settings.retrieval, RetrievalSettings)
