"""Pack-local evidence bundle and opaque tool argument builders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeVar

from domain.knowledge import ScoredChunk, SourceReference
from packs.software_delivery.errors import OrchestrationValidationError

_E = TypeVar("_E", bound=Exception)


def _require_text(
    value: object,
    field_name: str,
    error_type: type[_E] = OrchestrationValidationError,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"{field_name} must be non-empty")
    return value


def _require_sequence(
    value: object,
    field_name: str,
    error_type: type[_E] = OrchestrationValidationError,
) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise error_type(f"{field_name} must be a sequence, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class EvidenceBundleItem:
    """One retrieved evidence item with optional completeness for risk scoring."""

    reference: SourceReference
    text: str
    is_complete: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.reference, SourceReference):
            raise OrchestrationValidationError(
                f"reference must be a SourceReference, got {self.reference!r}"
            )
        _require_text(self.text, "text")
        if not isinstance(self.is_complete, bool):
            raise OrchestrationValidationError(
                f"is_complete must be a bool, got {self.is_complete!r}"
            )


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Typed multi-source evidence consumed by Software Delivery orchestration."""

    items: Sequence[EvidenceBundleItem]

    def __post_init__(self) -> None:
        items = _require_sequence(self.items, "items")
        if len(items) == 0:
            raise OrchestrationValidationError("items must be non-empty")
        normalized: list[EvidenceBundleItem] = []
        for item in items:
            if not isinstance(item, EvidenceBundleItem):
                raise OrchestrationValidationError(
                    f"items entries must be EvidenceBundleItem, got {item!r}"
                )
            normalized.append(item)
        object.__setattr__(self, "items", tuple(normalized))


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
