"""End-to-end ingest proof: the real Chroma adapter, no network, no seed corpus.

`ChromaSettings` is constructed directly and `load_settings()` is never called
here: it loads `.env` with `override=True`, so a developer's own configuration
would decide where this test writes (§3.1).

Embedding goes through `StubEmbeddingModel`, so the pipeline is exercised
end-to-end without an external API. Every chunk count asserted below is sliced
by hand from the fixture text against the window in use — never read back from
the value the use case produced.
"""

from pathlib import Path

import pytest

from application.contracts import IngestRequest
from application.ingest_knowledge import IngestKnowledge
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.config import ChromaSettings
from infrastructure.vectorstore.chroma import ChromaVectorStore
from test.doubles import StubEmbeddingModel, vector_for

COLLECTION = "kernector_knowledge"
CHUNK_SIZE = 10
CHUNK_OVERLAP = 2
# Any non-zero vector of the stub's width; `search` needs a probe, not a match.
PROBE = vector_for("probe")

# 26 characters. Step 8, so the windows are [0:10], [8:18], [16:26] = 3 chunks.
CONTENT_A = "abcdefghijklmnopqrstuvwxyz"
# 18 characters. Windows [0:10], [8:18] = 2 chunks.
CONTENT_B = "0123456789ABCDEFGH"

# A window wider than CONTENT_A collapses it to one chunk.
WIDE_CHUNK_SIZE = 30


def _settings(path: Path) -> ChromaSettings:
    return ChromaSettings(persist_path=path, collection=COLLECTION)


def _document(source_id: str, content: str) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)),
        content,
    )


def _both_documents() -> IngestRequest:
    return IngestRequest(
        documents=[_document("doc-a", CONTENT_A), _document("doc-b", CONTENT_B)]
    )


def _use_case(
    store: ChromaVectorStore,
    *,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> IngestKnowledge:
    return IngestKnowledge(
        StubEmbeddingModel(),
        store,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


def _record_count(store: ChromaVectorStore) -> int:
    """Records held, counted through the port rather than the vendor client."""
    return len(store.search(PROBE, 1000))


def _identities(store: ChromaVectorStore) -> list[tuple[str, int]]:
    """Every record's `(source_id, chunk_index)`, read back through `search`."""
    return sorted(
        (scored.chunk.reference.source_id, scored.chunk.index)
        for scored in store.search(PROBE, 1000)
    )


@pytest.fixture
def store(tmp_path: Path) -> ChromaVectorStore:
    return ChromaVectorStore(_settings(tmp_path / "chroma"))


@pytest.fixture
def ingested(store: ChromaVectorStore) -> ChromaVectorStore:
    """A real store already holding both documents at the default window."""
    _use_case(store).execute(_both_documents())
    return store


def test_ingest_stores_the_hand_computed_chunk_count(
    store: ChromaVectorStore,
) -> None:
    response = _use_case(store).execute(_both_documents())

    # 3 for doc-a plus 2 for doc-b, sliced by hand against size 10 / overlap 2.
    assert response.chunk_count == 5
    assert _record_count(store) == 5
    assert response.accepted_ids == ("doc-a", "doc-b")
    assert _identities(store) == [
        ("doc-a", 0),
        ("doc-a", 1),
        ("doc-a", 2),
        ("doc-b", 0),
        ("doc-b", 1),
    ]


def test_re_ingesting_unchanged_inputs_converges_on_the_same_count(
    ingested: ChromaVectorStore,
) -> None:
    response = _use_case(ingested).execute(_both_documents())

    assert response.chunk_count == 5
    assert _record_count(ingested) == 5


def test_re_ingesting_with_a_wider_window_removes_stale_chunks(
    ingested: ChromaVectorStore,
) -> None:
    response = _use_case(
        ingested, chunk_size=WIDE_CHUNK_SIZE, chunk_overlap=0
    ).execute(IngestRequest(documents=[_document("doc-a", CONTENT_A)]))

    assert response.chunk_count == 1
    # doc-a's indexes 1 and 2 are gone, so what remains is 1 + doc-b's 2.
    assert _record_count(ingested) == 3
    assert ("doc-a", 1) not in _identities(ingested)
    assert ("doc-a", 2) not in _identities(ingested)


def test_sources_absent_from_the_request_remain_present(
    ingested: ChromaVectorStore,
) -> None:
    _use_case(ingested, chunk_size=WIDE_CHUNK_SIZE, chunk_overlap=0).execute(
        IngestRequest(documents=[_document("doc-a", CONTENT_A)])
    )

    assert _identities(ingested) == [("doc-a", 0), ("doc-b", 0), ("doc-b", 1)]


def test_the_final_state_persists_after_reopening_the_store(
    tmp_path: Path, ingested: ChromaVectorStore
) -> None:
    """Reopened on the same path, per the plan's acceptance proof.

    Same-process reopen, so chromadb's cached client system is in play. True
    cross-process durability is proven by
    `test/infrastructure/vectorstore/test_chroma.py::test_records_survive_a_process_restart`,
    which this deliberately does not duplicate.
    """
    _use_case(ingested, chunk_size=WIDE_CHUNK_SIZE, chunk_overlap=0).execute(
        IngestRequest(documents=[_document("doc-a", CONTENT_A)])
    )

    reopened = ChromaVectorStore(_settings(tmp_path / "chroma"))

    assert _record_count(reopened) == 3
    assert _identities(reopened) == [("doc-a", 0), ("doc-b", 0), ("doc-b", 1)]
