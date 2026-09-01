"""Map retrieved scored chunks to opaque Software Delivery tool arguments."""

from collections.abc import Sequence

from domain.knowledge import ScoredChunk


def evidence_items_from_hits(hits: Sequence[ScoredChunk]) -> list[dict[str, object]]:
    """Project retrieval hits into tool evidence dicts.

    Args:
        hits (Sequence[ScoredChunk]): Relevant ranked chunks with provenance.

    Returns:
        list[dict[str, object]]: Opaque evidence items. ``is_complete`` is true
        only when chunk metadata extra contains ``is_complete`` as ``"true"``.
    """
    items: list[dict[str, object]] = []
    for hit in hits:
        extra = hit.chunk.metadata.extra
        items.append(
            {
                "source_id": hit.chunk.reference.source_id,
                "source_type": hit.chunk.reference.source_type,
                "text": hit.chunk.content,
                "is_complete": extra.get("is_complete") == "true",
            }
        )
    return items


def base_tool_arguments(
    target: str, hits: Sequence[ScoredChunk]
) -> dict[str, object]:
    """Build the shared ``target`` + ``evidence`` payload for domain tools.

    Args:
        target (str): Assessment subject forwarded unchanged.
        hits (Sequence[ScoredChunk]): Relevant ranked chunks.

    Returns:
        dict[str, object]: Opaque JSON-compatible tool arguments.
    """
    return {"target": target, "evidence": evidence_items_from_hits(hits)}
