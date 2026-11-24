"""Plain retrieval keeps multiple chunks per source after exact/hybrid merge."""

from __future__ import annotations

from application.contracts import RetrieveRequest
from application.retrieve_knowledge import RetrieveKnowledge
from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    SourceMetadata,
    SourceReference,
)
from test.doubles import InMemoryVectorStore, StubEmbeddingModel, vector_for


def _chunk(source_id: str, index: int, content: str) -> DocumentChunk:
    return DocumentChunk(
        metadata=SourceMetadata(
            SourceReference(source_id, "knowledge_document"),
            title=source_id,
        ),
        index=index,
        content=content,
    )


def test_plain_retrieval_keeps_multiple_chunks_from_one_source() -> None:
    store = InMemoryVectorStore()
    chunks = (
        _chunk("doc-a", 0, "login step one"),
        _chunk("doc-a", 1, "login step two"),
        _chunk("doc-a", 2, "login step three"),
        _chunk("doc-b", 0, "logout flow"),
    )
    store.upsert(
        [EmbeddedChunk(chunk=chunk, vector=vector_for(chunk.content)) for chunk in chunks]
    )
    retrieve = RetrieveKnowledge(
        StubEmbeddingModel(),
        store,
        max_input_length=10_000,
    )

    response = retrieve.execute(
        RetrieveRequest(query="how does login work", retrieval_limit=4)
    )

    assert [(hit.chunk.source_id, hit.chunk.index) for hit in response.hits] == [
        ("doc-a", 0),
        ("doc-a", 1),
        ("doc-a", 2),
        ("doc-b", 0),
    ]
