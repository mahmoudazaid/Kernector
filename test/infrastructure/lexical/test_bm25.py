"""Behavior of Bm25LexicalIndex observed through the LexicalIndex seam."""

from domain.knowledge import (
    DocumentChunk,
    EmbeddedChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.lexical.bm25 import Bm25LexicalIndex
from test.doubles import InMemoryLexicalIndex, vector_for


def _chunk(
    source_id: str,
    content: str,
    *,
    extra: dict[str, str] | None = None,
    index: int = 0,
) -> DocumentChunk:
    return DocumentChunk(
        metadata=SourceMetadata(
            SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT),
            extra=extra or {},
        ),
        index=index,
        content=content,
    )


def _embed(chunk: DocumentChunk) -> EmbeddedChunk:
    return EmbeddedChunk(chunk=chunk, vector=vector_for(chunk.content))


def test_in_memory_lexical_empty_corpus_returns_no_hits() -> None:
    assert InMemoryLexicalIndex().search("anything", 5) == ()


def test_in_memory_lexical_filters_apply_before_limit() -> None:
    index = InMemoryLexicalIndex()
    index.upsert(
        [
            _embed(_chunk("a", "restart runbook steps", extra={"doc_type": "policy"})),
            _embed(_chunk("b", "restart runbook steps", extra={"doc_type": "runbook"})),
            _embed(_chunk("c", "restart runbook steps", extra={"doc_type": "runbook"})),
        ]
    )

    hits = index.search(
        "restart runbook",
        1,
        metadata_filters={"doc_type": "runbook"},
    )

    assert [hit.chunk.source_id for hit in hits] == ["b"]


def test_bm25_empty_corpus_returns_no_hits() -> None:
    assert Bm25LexicalIndex().search("ERR-4021", 5) == ()


def test_bm25_ranks_exact_token_match_above_unrelated() -> None:
    # BM25Okapi IDF is zero for df=1 when N=2; use N>=3 so scores discriminate.
    index = Bm25LexicalIndex()
    index.upsert(
        [
            _embed(_chunk("error", "Error ERR-4021 means the API key is missing")),
            _embed(_chunk("other", "Deploy the service with blue-green rollout")),
            _embed(_chunk("third", "Unrelated capacity planning notes")),
        ]
    )

    hits = index.search("ERR-4021", 3)

    assert hits[0].chunk.source_id == "error"
    assert hits[0].score > hits[1].score


def test_bm25_filters_apply_before_limit() -> None:
    index = Bm25LexicalIndex()
    index.upsert(
        [
            _embed(
                _chunk(
                    "policy",
                    "ERR-4021 policy note about keys",
                    extra={"doc_type": "policy"},
                )
            ),
            _embed(
                _chunk(
                    "runbook",
                    "ERR-4021 runbook recovery steps",
                    extra={"doc_type": "runbook"},
                )
            ),
        ]
    )

    hits = index.search(
        "ERR-4021",
        1,
        metadata_filters={"doc_type": "runbook"},
    )

    assert [hit.chunk.source_id for hit in hits] == ["runbook"]


def test_bm25_delete_source_removes_chunks_from_search() -> None:
    index = Bm25LexicalIndex()
    index.upsert(
        [
            _embed(_chunk("keep", "alpha token unique-keep")),
            _embed(_chunk("drop", "alpha token unique-drop")),
        ]
    )
    index.delete_source(SourceReference("drop", SourceType.KNOWLEDGE_DOCUMENT))

    hits = index.search("unique-drop", 5)

    assert hits == () or all(hit.chunk.source_id != "drop" for hit in hits)


def test_bm25_upsert_replaces_same_identity() -> None:
    index = Bm25LexicalIndex()
    index.upsert([_embed(_chunk("doc", "obsolete phrase xyzzy"))])
    index.upsert([_embed(_chunk("doc", "replacement phrase plugh"))])

    obsolete = index.search("xyzzy", 5)
    replacement = index.search("plugh", 5)

    assert all(hit.chunk.source_id != "doc" or "xyzzy" not in hit.chunk.content for hit in obsolete)
    assert replacement[0].chunk.content == "replacement phrase plugh"
