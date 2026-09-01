"""Pack-local evidence bundle and opaque tool argument builders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from domain.knowledge import ScoredChunk, SourceReference


@dataclass(frozen=True, slots=True)
class EvidenceBundleItem:
    """One retrieved evidence item with optional completeness for risk scoring."""

    reference: SourceReference
    text: str
    is_complete: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Typed multi-source evidence consumed by Software Delivery orchestration."""

    items: Sequence[EvidenceBundleItem]

    def __post_init__(self) -> None:
        if isinstance(self.items, (str, bytes)) or not isinstance(self.items, Sequence):
            raise ValueError(f"items must be a sequence, got {self.items!r}")
        object.__setattr__(self, "items", tuple(self.items))


def evidence_bundle_from_hits(hits: Sequence[ScoredChunk]) -> EvidenceBundle:
    """Build a deduplicated evidence bundle from retrieval hits.

    Items sharing the same ``(source_type, source_id)`` merge into one row.
    Text is joined with blank lines; ``is_complete`` is true when any merged
    chunk metadata extra marks ``is_complete`` as ``"true"``.
    """
    merged: dict[tuple[str, str], EvidenceBundleItem] = {}
    order: list[tuple[str, str]] = []
    for hit in hits:
        ref = hit.chunk.reference
        key = (ref.source_type, ref.source_id)
        complete = hit.chunk.metadata.extra.get("is_complete") == "true"
        if key not in merged:
            order.append(key)
            merged[key] = EvidenceBundleItem(ref, hit.chunk.content, complete)
            continue
        existing = merged[key]
        text = existing.text if not existing.text else f"{existing.text}\n\n{hit.chunk.content}"
        merged[key] = EvidenceBundleItem(
            existing.reference,
            text,
            existing.is_complete or complete,
        )
    return EvidenceBundle(tuple(merged[key] for key in order))


def risk_tool_arguments(target: str, bundle: EvidenceBundle) -> dict[str, object]:
    """Build opaque arguments for ``software_delivery.risk_score``."""
    return {
        "target": target,
        "evidence": [
            {
                "source_id": item.reference.source_id,
                "source_type": item.reference.source_type,
                "text": item.text,
                "is_complete": item.is_complete,
            }
            for item in bundle.items
        ],
    }


def generate_test_tool_arguments(
    target: str,
    bundle: EvidenceBundle,
    output_style: str,
) -> dict[str, object]:
    """Build opaque arguments for ``software_delivery.generate_test_cases``.

    Test-generation evidence must not include ``is_complete``.
    """
    return {
        "target": target,
        "output_style": output_style,
        "evidence": [
            {
                "source_id": item.reference.source_id,
                "source_type": item.reference.source_type,
                "text": item.text,
            }
            for item in bundle.items
        ],
    }


def export_tool_arguments(result: Mapping[str, object]) -> dict[str, object]:
    """Build opaque export arguments from a generate-test-cases JSON object."""
    return {
        "output_style": result["output_style"],
        "test_cases": result["test_cases"],
    }
