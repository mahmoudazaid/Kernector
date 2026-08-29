"""Assemble Citation values from retrieved ScoredChunk hits."""

from collections.abc import Sequence

from application.contracts import Citation
from domain.knowledge import ScoredChunk


def build_citations(hits: Sequence[ScoredChunk]) -> tuple[Citation, ...]:
    """Map each hit to a Citation, preserving order and duplicates.

    Args:
        hits: Ranked retrieval hits with full provenance on each chunk.

    Returns:
        One Citation per hit. Empty input yields ``()``.
    """
    return tuple(
        Citation(
            reference=hit.chunk.reference,
            quote=hit.chunk.content,
            chunk_index=hit.chunk.index,
        )
        for hit in hits
    )
