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
import pytest


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
    # BM25Okapi IDF is zero for df=1 when N=2; use N>=3 so scores discriminate
    # among overlapping docs. Unrelated docs share no query tokens and are omitted.
    index = Bm25LexicalIndex()
    index.upsert(
        [
            _embed(_chunk("error", "Error ERR-4021 means the API key is missing")),
            _embed(_chunk("other", "Deploy the service with blue-green rollout")),
            _embed(_chunk("third", "Unrelated capacity planning notes")),
            _embed(_chunk("also", "Also mentions ERR-4021 in a footnote")),
        ]
    )

    hits = index.search("ERR-4021", 3)

    assert {hit.chunk.source_id for hit in hits} <= {"error", "also"}
    assert hits[0].chunk.source_id in {"error", "also"}
    assert all("err-4021" in hit.chunk.content.casefold() for hit in hits)


def test_bm25_unrelated_query_returns_no_hits() -> None:
    index = Bm25LexicalIndex()
    index.upsert(
        [
            _embed(_chunk("a", "restart runbook steps")),
            _embed(_chunk("b", "deploy blue-green rollout")),
            _embed(_chunk("c", "capacity planning notes")),
        ]
    )

    assert index.search("zzzz-not-present-qqqq", 5) == ()


def test_bm25_keeps_overlap_even_when_raw_score_is_non_positive() -> None:
    # N=2 and df=1 → BM25Okapi IDF cancels to 0.0 for the matching term.
    index = Bm25LexicalIndex()
    index.upsert(
        [
            _embed(_chunk("hit", "unique-token-xyz appears here")),
            _embed(_chunk("miss", "totally different deploy notes")),
        ]
    )

    hits = index.search("unique-token-xyz", 5)

    assert [hit.chunk.source_id for hit in hits] == ["hit"]
    assert hits[0].score == pytest.approx(0.0)


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


def test_bm25_matches_arabic_query_to_arabic_content() -> None:
    index = Bm25LexicalIndex()
    index.upsert(
        [
            _embed(_chunk("ar", "إعادة تشغيل خدمة الدفع تتطلب تصريفاً أولاً")),
            _embed(_chunk("en", "Restart the payment service by draining first")),
            _embed(_chunk("other", "Capacity planning notes only")),
        ]
    )

    hits = index.search("تصريفاً", 3)

    assert hits[0].chunk.source_id == "ar"
    assert hits[0].score > 0


def test_bm25_matches_mixed_arabic_and_english() -> None:
    index = Bm25LexicalIndex()
    index.upsert(
        [
            _embed(_chunk("mixed", "Error ERR-4021 مفتاح API مفقود")),
            _embed(_chunk("en", "Unrelated English rollout notes")),
            _embed(_chunk("ar", "ملاحظات غير ذات صلة")),
        ]
    )

    hits = index.search("ERR-4021 مفتاح", 3)

    assert hits[0].chunk.source_id == "mixed"


def test_bm25_punctuation_only_corpus_returns_empty_without_error() -> None:
    index = Bm25LexicalIndex()
    index.upsert(
        [
            _embed(_chunk("dots", "...!!!???")),
            _embed(_chunk("commas", ",,,;;;")),
        ]
    )

    assert index.search("anything", 5) == ()
    assert index.search("...", 5) == ()


def test_bm25_tokenless_query_returns_empty() -> None:
    index = Bm25LexicalIndex()
    index.upsert(
        [
            _embed(_chunk("a", "restart runbook")),
            _embed(_chunk("b", "deploy service")),
            _embed(_chunk("c", "capacity notes")),
        ]
    )

    assert index.search("...", 5) == ()
    assert index.search("", 5) == ()


def test_tokenize_preserves_hyphenated_identifier() -> None:
    from infrastructure.lexical.bm25 import tokenize

    assert "err-4021" in tokenize("see ERR-4021 now")
