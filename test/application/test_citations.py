"""Unit tests for assembling Citation values from ScoredChunk hits."""

from application.citations import build_citations
from application.contracts import Citation
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)


def _hit(
    *,
    source_id: str = "doc-1",
    content: str = "chunk text",
    index: int = 0,
    score: float = 0.9,
) -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(
                SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)
            ),
            index=index,
            content=content,
        ),
        score=score,
    )


def test_empty_hits_produce_empty_citations() -> None:
    assert build_citations(()) == ()


def test_single_hit_maps_to_citation_with_full_quote_and_index() -> None:
    reference = SourceReference("runbook-7", SourceType.KNOWLEDGE_DOCUMENT)
    hit = ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(reference),
            index=3,
            content="restart the worker process",
        ),
        score=0.85,
    )

    citations = build_citations((hit,))

    assert citations == (
        Citation(
            reference=reference,
            quote="restart the worker process",
            chunk_index=3,
        ),
    )
    assert citations[0].reference is hit.chunk.reference


def test_citations_preserve_hit_order() -> None:
    first = _hit(source_id="doc-a", content="alpha", index=0)
    second = _hit(source_id="doc-b", content="beta", index=1)

    citations = build_citations((first, second))

    assert citations == (
        Citation(
            reference=first.chunk.reference,
            quote="alpha",
            chunk_index=0,
        ),
        Citation(
            reference=second.chunk.reference,
            quote="beta",
            chunk_index=1,
        ),
    )


def test_duplicate_hits_produce_separate_citations() -> None:
    hit = _hit(source_id="doc-1", content="same chunk", index=2)

    citations = build_citations((hit, hit))

    expected = Citation(
        reference=hit.chunk.reference,
        quote="same chunk",
        chunk_index=2,
    )
    assert citations == (expected, expected)
    assert len(citations) == 2
