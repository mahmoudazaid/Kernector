"""End-to-end proof: rewritten query changes which chunks rank first in Chroma.

Uses real ``ChromaVectorStore`` and ``StubEmbeddingModel`` so similarity ranking
is observable without a network call. ``InMemoryVectorStore`` ignores the query
vector, so this ranking proof cannot live in the unit suite.
"""

from pathlib import Path

import pytest

from application.contracts import IngestRequest, RetrieveRequest
from application.ingest_knowledge import IngestKnowledge
from application.retrieve_knowledge import RetrieveKnowledge
from application.rewrite_and_retrieve import RewriteAndRetrieveKnowledge
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.config import ChromaSettings
from infrastructure.vectorstore.chroma import ChromaVectorStore
from test.doubles import StubEmbeddingModel, StubQueryRewriter

COLLECTION = "kernector_knowledge"
CHUNK_SIZE = 200
CHUNK_OVERLAP = 0

MATCHING_CONTENT = "payment service outage recovery steps"
OTHER_CONTENT = "office wifi password reset procedure"


def _settings(path: Path) -> ChromaSettings:
    return ChromaSettings(persist_path=path, collection=COLLECTION)


def _document(source_id: str, content: str) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT),
        ),
        content,
    )


@pytest.fixture
def store(tmp_path: Path) -> ChromaVectorStore:
    return ChromaVectorStore(_settings(tmp_path / "chroma"))


def test_rewritten_query_ranks_matching_chunk_first(
    store: ChromaVectorStore,
) -> None:
    embedding = StubEmbeddingModel()
    ingest = IngestKnowledge(
        embedding,
        store,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    ingest.execute(
        IngestRequest(
            documents=[
                _document("outage", MATCHING_CONTENT),
                _document("wifi", OTHER_CONTENT),
            ]
        )
    )

    rewritten = MATCHING_CONTENT
    use_case = RewriteAndRetrieveKnowledge(
        StubQueryRewriter(rewritten),
        RetrieveKnowledge(embedding, store),
    )

    response = use_case.execute(
        RetrieveRequest(query="what broke last week?", retrieval_limit=2)
    )

    assert response.original_query == "what broke last week?"
    assert response.rewritten_query == rewritten
    assert response.hits[0].chunk.source_id == "outage"
    assert MATCHING_CONTENT in response.hits[0].chunk.content
