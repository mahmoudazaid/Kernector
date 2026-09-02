"""DualWriteVectorStore keeps VectorStore and LexicalIndex in sync."""

from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.vectorstore.dual_write import DualWriteVectorStore
from test.doubles import InMemoryLexicalIndex, InMemoryVectorStore, vector_for


def _chunk(source_id: str, content: str, *, index: int = 0) -> DocumentChunk:
    return DocumentChunk(
        metadata=SourceMetadata(
            SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)
        ),
        index=index,
        content=content,
    )


def _embed(chunk: DocumentChunk) -> EmbeddedChunk:
    return EmbeddedChunk(chunk=chunk, vector=vector_for(chunk.content))


def test_dual_write_upsert_mirrors_into_lexical_index() -> None:
    vector = InMemoryVectorStore()
    lexical = InMemoryLexicalIndex()
    store = DualWriteVectorStore(vector, lexical)

    store.upsert([_embed(_chunk("doc", "restart runbook"))])

    assert "doc" in {item.chunk.source_id for item in vector.records.values()}
    assert "doc" in {item.chunk.source_id for item in lexical.records.values()}
    assert lexical.search("restart", 1)[0].chunk.source_id == "doc"


def test_dual_write_delete_source_removes_from_both() -> None:
    vector = InMemoryVectorStore()
    lexical = InMemoryLexicalIndex()
    store = DualWriteVectorStore(vector, lexical)
    store.upsert(
        [
            _embed(_chunk("keep", "alpha keep-token")),
            _embed(_chunk("drop", "alpha drop-token")),
        ]
    )

    store.delete_source(SourceReference("drop", SourceType.KNOWLEDGE_DOCUMENT))

    assert all(item.chunk.source_id != "drop" for item in vector.records.values())
    assert all(item.chunk.source_id != "drop" for item in lexical.records.values())
    assert all(
        hit.chunk.source_id != "drop" for hit in lexical.search("drop-token", 5)
    )


def test_dual_write_search_delegates_to_vector_store_only() -> None:
    vector = InMemoryVectorStore()
    lexical = InMemoryLexicalIndex()
    store = DualWriteVectorStore(vector, lexical)
    store.upsert([_embed(_chunk("doc", "content about widgets"))])

    hits = store.search(vector_for("anything"), 1)

    assert len(hits) == 1
    assert hits[0].chunk.source_id == "doc"
    assert hits[0].score == 1.0
