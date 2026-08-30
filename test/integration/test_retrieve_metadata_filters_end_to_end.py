"""End-to-end proof: ingest with opaque `extra`, then retrieve with filters.

Uses real Chroma and `StubEmbeddingModel` so caller-supplied metadata becomes
filterable through the shared pipeline without a network call.
"""

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
from infrastructure.config import ChromaSettings
from infrastructure.vectorstore.chroma import ChromaVectorStore
from test.doubles import StubEmbeddingModel

COLLECTION = "kernector_knowledge"
# Wider than every fixture body so each document yields exactly one chunk.
CHUNK_SIZE = 200
CHUNK_OVERLAP = 0


def _settings(path: Path) -> ChromaSettings:
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


@pytest.fixture
def store(tmp_path: Path) -> ChromaVectorStore:
    return ChromaVectorStore(_settings(tmp_path / "chroma"))


def test_ingested_extra_metadata_is_filterable_on_retrieve(
    store: ChromaVectorStore,
) -> None:
    embedding = StubEmbeddingModel()
    ingest = IngestKnowledge(
        embedding,
        store,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    retrieve = RetrieveKnowledge(embedding, store, max_input_length=10_000)

    ingest.execute(
        IngestRequest(
            documents=[
                _document(
                    "runbook-1",
                    "Restart the payment service by draining connections first.",
                    extra={"doc_type": "runbook", "severity": "high"},
                ),
                _document(
                    "policy-1",
                    "Restart windows require change-management approval.",
                    extra={"doc_type": "policy", "severity": "high"},
                ),
                _document(
                    "runbook-low",
                    "Optional cache warm-up after a restart.",
                    extra={"doc_type": "runbook", "severity": "low"},
                ),
            ]
        )
    )

    filtered = retrieve.execute(
        RetrieveRequest(
            query="how do we restart payment?",
            retrieval_limit=10,
            metadata_filters={"doc_type": "runbook", "severity": "high"},
        )
    )

    assert [hit.chunk.source_id for hit in filtered.hits] == ["runbook-1"]
    hit = filtered.hits[0]
    assert hit.chunk.reference == SourceReference(
        "runbook-1", SourceType.KNOWLEDGE_DOCUMENT
    )
    assert dict(hit.chunk.metadata.extra) == {
        "doc_type": "runbook",
        "severity": "high",
    }
    assert "Restart the payment service" in hit.chunk.content

    missing = retrieve.execute(
        RetrieveRequest(
            query="restart",
            retrieval_limit=10,
            metadata_filters={"doc_type": "runbook", "component": "payments"},
        )
    )
    assert missing.hits == ()

    unfiltered = retrieve.execute(
        RetrieveRequest(query="restart", retrieval_limit=10)
    )
    assert {hit.chunk.source_id for hit in unfiltered.hits} == {
        "runbook-1",
        "policy-1",
        "runbook-low",
    }
