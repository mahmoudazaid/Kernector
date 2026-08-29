"""Heterogeneous knowledge-corpus ingest against real Chroma, offline.

`ChromaSettings` is built directly; ``load_settings()`` is never called here so
a local ``.env`` cannot redirect persistence. Embedding uses
``StubEmbeddingModel`` so no network is required.

Category diversity is proven by provenance metadata on stored chunks, not by
CLI switches or per-``doc_type`` code paths.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.contracts import IngestRequest
from application.ingest_knowledge import IngestKnowledge
from domain.knowledge import SourceType
from infrastructure.config import ChromaSettings
from infrastructure.knowledge.corpus import load_knowledge_corpus
from infrastructure.vectorstore.chroma import ChromaVectorStore
from test.doubles import StubEmbeddingModel, vector_for

COLLECTION = "kernector_knowledge_corpus_e2e"
# Larger than every fixture body so each document yields exactly one chunk.
CHUNK_SIZE = 10_000
CHUNK_OVERLAP = 0
PROBE = vector_for("probe")

_FIXTURE_RECORDS = [
    {
        "source_id": "openapi-payments-001",
        "title": "Create payment endpoint",
        "doc_type": "openapi",
        "content": "POST /payments creates a payment for a customer.",
        "status": "approved",
        "version": "1.0",
        "tags": ["payments", "api"],
        "severity": None,
        "component": "payment-service",
        "source_name": "Payments API",
        "source_url": "https://example.test/openapi.json",
    },
    {
        "source_id": "bug-auth-001",
        "title": "Session cookie not cleared on logout",
        "doc_type": "bug",
        "content": "Expected: after logout the session cookie is removed.",
        "status": "approved",
        "version": "1.0",
        "tags": ["auth", "session"],
        "severity": "high",
        "component": "auth",
        "source_name": "QA defect triage",
    },
    {
        "source_id": "srs-auth-001",
        "title": "Authentication session lifetime",
        "doc_type": "srs",
        "content": "REQ-AUTH-12: sessions expire after 30 minutes of inactivity.",
        "status": "approved",
        "version": "1.0",
        "tags": ["authentication", "sessions"],
        "severity": None,
        "component": "auth",
        "source_name": "Kernector SRS",
    },
]


def _write_fixture(path: Path) -> Path:
    path.write_text(json.dumps(_FIXTURE_RECORDS), encoding="utf-8")
    return path


def _settings(path: Path) -> ChromaSettings:
    return ChromaSettings(persist_path=path, collection=COLLECTION)


def _use_case(store: ChromaVectorStore) -> IngestKnowledge:
    return IngestKnowledge(
        StubEmbeddingModel(),
        store,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )


def _record_count(store: ChromaVectorStore) -> int:
    return len(store.search(PROBE, 1000))


def _chunks_by_source(store: ChromaVectorStore) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for scored in store.search(PROBE, 1000):
        source_id = scored.chunk.reference.source_id
        grouped.setdefault(source_id, []).append(scored.chunk)
    return grouped


@pytest.fixture
def corpus_path(tmp_path: Path) -> Path:
    return _write_fixture(tmp_path / "corpus.json")


@pytest.fixture
def store(tmp_path: Path) -> ChromaVectorStore:
    return ChromaVectorStore(_settings(tmp_path / "chroma"))


def test_heterogeneous_corpus_preserves_doc_type_and_provenance(
    corpus_path: Path, store: ChromaVectorStore
) -> None:
    documents = load_knowledge_corpus(corpus_path)
    # Three categories; composition does not special-case any of them.
    assert {document.metadata.extra["doc_type"] for document in documents} == {
        "openapi",
        "bug",
        "srs",
    }

    response = _use_case(store).execute(IngestRequest(documents=documents))

    # One chunk per document at CHUNK_SIZE 10000 / overlap 0.
    assert response.chunk_count == 3
    assert list(response.accepted_ids) == [
        "openapi-payments-001",
        "bug-auth-001",
        "srs-auth-001",
    ]
    assert _record_count(store) == 3

    by_source = _chunks_by_source(store)
    assert set(by_source) == {
        "openapi-payments-001",
        "bug-auth-001",
        "srs-auth-001",
    }

    openapi = by_source["openapi-payments-001"][0]
    assert openapi.metadata.extra["doc_type"] == "openapi"
    assert openapi.metadata.extra["tags_json"] == '["payments","api"]'
    assert openapi.metadata.extra["source_name"] == "Payments API"
    assert openapi.metadata.extra["source_url"] == "https://example.test/openapi.json"
    assert openapi.reference.source_type == SourceType.KNOWLEDGE_DOCUMENT

    bug = by_source["bug-auth-001"][0]
    assert bug.metadata.extra["doc_type"] == "bug"
    assert bug.metadata.extra["severity"] == "high"
    assert bug.metadata.extra["source_name"] == "QA defect triage"
    assert bug.reference.source_type == SourceType.KNOWLEDGE_DOCUMENT

    srs = by_source["srs-auth-001"][0]
    assert srs.metadata.extra["doc_type"] == "srs"
    assert srs.metadata.extra["source_name"] == "Kernector SRS"
    assert srs.reference.source_type == SourceType.KNOWLEDGE_DOCUMENT

    assert {
        scored.chunk.reference.source_type for scored in store.search(PROBE, 1000)
    } == {SourceType.KNOWLEDGE_DOCUMENT}


def test_re_ingesting_heterogeneous_corpus_keeps_chunk_count(
    corpus_path: Path, store: ChromaVectorStore
) -> None:
    documents = load_knowledge_corpus(corpus_path)
    use_case = _use_case(store)
    first = use_case.execute(IngestRequest(documents=documents))
    identities = sorted(
        (scored.chunk.reference.source_id, scored.chunk.index)
        for scored in store.search(PROBE, 1000)
    )
    doc_types = {
        scored.chunk.reference.source_id: scored.chunk.metadata.extra["doc_type"]
        for scored in store.search(PROBE, 1000)
    }

    second = use_case.execute(IngestRequest(documents=documents))

    assert second.chunk_count == first.chunk_count == 3
    assert _record_count(store) == 3
    assert sorted(
        (scored.chunk.reference.source_id, scored.chunk.index)
        for scored in store.search(PROBE, 1000)
    ) == identities
    assert {
        scored.chunk.reference.source_id: scored.chunk.metadata.extra["doc_type"]
        for scored in store.search(PROBE, 1000)
    } == doc_types
    assert doc_types == {
        "openapi-payments-001": "openapi",
        "bug-auth-001": "bug",
        "srs-auth-001": "srs",
    }
