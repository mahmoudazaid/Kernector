"""Typed citation buffer for agentic retrieval (not recovered from tool text)."""

from __future__ import annotations

from collections.abc import Sequence

from application.citations import build_citations
from application.contracts import Citation
from domain.knowledge import ScoredChunk


class RetrievalCitationChannel:
    """Per-turn buffer of citations recorded by retrieve tool invocations.

    Callers clear before a turn and ``drain`` after the agent finishes. Citations
    are typed ``Citation`` values built from ``ScoredChunk`` hits — never parsed
    from the model-facing tool string.
    """

    def __init__(self) -> None:
        self._hits: list[ScoredChunk] = []

    def clear(self) -> None:
        """Drop any recorded hits for a new agent turn."""
        self._hits.clear()

    def record(self, hits: Sequence[ScoredChunk]) -> None:
        """Append retrieval hits for later citation drain."""
        self._hits.extend(hits)

    def drain(self) -> tuple[Citation, ...]:
        """Return citations for recorded hits and clear the buffer."""
        citations = build_citations(tuple(self._hits))
        self._hits.clear()
        return citations
