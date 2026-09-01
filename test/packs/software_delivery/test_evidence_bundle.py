"""Tests for Software Delivery evidence bundle mapping."""

from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
)
from packs.software_delivery.evidence_bundle import (
    evidence_bundle_from_hits,
    risk_tool_arguments,
    generate_test_tool_arguments,
)


def _hit(
    *,
    source_id: str = "US-1",
    source_type: str = "user_story",
    content: str = "Need MFA",
    extra: dict[str, str] | None = None,
) -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(
                SourceReference(source_id, source_type),
                extra=extra or {},
            ),
            index=0,
            content=content,
        ),
        score=0.9,
    )


def test_risk_payload_includes_is_complete_test_payload_does_not() -> None:
    bundle = evidence_bundle_from_hits(
        [_hit(extra={"is_complete": "true"}), _hit(source_id="US-2")]
    )
    risk = risk_tool_arguments("Assess MFA", bundle)
    test = generate_test_tool_arguments("Assess MFA", bundle, "steps")

    assert risk["evidence"][0]["is_complete"] is True
    assert "is_complete" not in test["evidence"][0]
    assert "is_complete" not in test["evidence"][1]


def test_duplicate_source_references_merge_text_and_completeness() -> None:
    bundle = evidence_bundle_from_hits(
        [
            _hit(content="part one"),
            _hit(content="part two", extra={"is_complete": "true"}),
        ]
    )

    assert len(bundle.items) == 1
    assert bundle.items[0].text == "part one\n\npart two"
    assert bundle.items[0].is_complete is True


def test_test_payload_preserves_source_references() -> None:
    bundle = evidence_bundle_from_hits(
        [_hit(source_id="US-9", source_type="user_story")]
    )
    payload = generate_test_tool_arguments("Assess MFA", bundle, "gherkin")
    item = payload["evidence"][0]
    assert item["source_id"] == "US-9"
    assert item["source_type"] == "user_story"
    assert item["text"] == "Need MFA"
