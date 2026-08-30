"""Grounded-RAG system policy is mandatory and non-pack-selectable."""

from application.grounded_rag_policy import GROUNDED_RAG_SYSTEM


def test_grounded_rag_policy_requires_grounding_citations_and_honesty() -> None:
    text = GROUNDED_RAG_SYSTEM.lower()
    assert "untrusted" in text
    assert "citation" in text or "citing" in text
    assert "insufficient" in text
    assert "invent" in text
    assert GROUNDED_RAG_SYSTEM.strip()
