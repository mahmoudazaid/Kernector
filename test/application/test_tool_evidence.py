"""Map retrieved hits to opaque tool evidence arguments."""

from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from application.tool_evidence import base_tool_arguments, evidence_items_from_hits


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


def test_evidence_items_from_hits_copy_provenance_and_text() -> None:
    items = evidence_items_from_hits([_hit()])
    assert items == [
        {
            "source_id": "US-1",
            "source_type": "user_story",
            "text": "Need MFA",
            "is_complete": False,
        }
    ]


def test_evidence_items_mark_complete_from_metadata_extra() -> None:
    items = evidence_items_from_hits(
        [_hit(extra={"is_complete": "true"}), _hit(source_id="US-2")]
    )
    assert items[0]["is_complete"] is True
    assert items[1]["is_complete"] is False


def test_base_tool_arguments_include_target_and_evidence() -> None:
    args = base_tool_arguments("Assess MFA", [_hit()])
    assert args["target"] == "Assess MFA"
    assert args["evidence"][0]["source_id"] == "US-1"  # type: ignore[index]


def test_knowledge_document_source_type_is_preserved() -> None:
    items = evidence_items_from_hits(
        [_hit(source_type=SourceType.KNOWLEDGE_DOCUMENT, source_id="doc-1")]
    )
    assert items[0]["source_type"] == SourceType.KNOWLEDGE_DOCUMENT
    assert items[0]["source_id"] == "doc-1"
