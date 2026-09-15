"""Serialize and deserialize test-design drafts for opaque storage."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from domain.knowledge import SourceReference
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.models import (
    COVERAGE_CATEGORIES_DISPLAY,
    DRAFT_STATUSES,
    DRAFT_STATUSES_DISPLAY,
    TestCandidate,
    TestCoverageDraft,
    coerce_coverage_category,
)

DRAFT_SCHEMA_VERSION = 1


def _normalize_stored_category(raw: str) -> str:
    coerced = coerce_coverage_category(raw)
    if coerced is not None:
        return coerced
    raise TestDesignValidationError(
        f"category must be one of {COVERAGE_CATEGORIES_DISPLAY}"
    )


def _normalize_stored_status(raw: str) -> str:
    # Pre-#300 drafts used scenario_editing after confirm; treat as ready.
    if raw == "scenario_editing":
        return "ready"
    if raw not in DRAFT_STATUSES:
        raise TestDesignValidationError(
            f"status must be one of {DRAFT_STATUSES_DISPLAY}"
        )
    return raw


def encode_draft_payload(draft: TestCoverageDraft) -> str:
    """Encode a typed draft into an opaque JSON payload with schema_version."""
    body = {
        "schema_version": DRAFT_SCHEMA_VERSION,
        "workspace_id": draft.workspace_id,
        "conversation_id": draft.conversation_id,
        "source_reference": {
            "source_type": draft.source_reference.source_type,
            "source_id": draft.source_reference.source_id,
        },
        "ticket_identifier": draft.ticket_identifier,
        "status": draft.status,
        "candidates": [_encode_candidate(item) for item in draft.candidates],
    }
    return json.dumps(body, separators=(",", ":"), sort_keys=True)


def decode_draft_payload(
    payload: str,
    *,
    draft_id: str,
    version: int,
) -> TestCoverageDraft:
    """Decode an opaque payload into a typed draft.

    Legacy ``scenarios`` and ``coverage_gaps`` keys are ignored.
    ``scenario_editing`` status maps to ``ready``.

    Raises:
        TestDesignValidationError: Payload JSON or draft shape is invalid.
    """
    if not isinstance(payload, str):
        raise TestDesignValidationError(
            f"payload must be a string, got {type(payload).__name__}"
        )
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as error:
        raise TestDesignValidationError("payload must be valid JSON") from error
    if not isinstance(raw, dict):
        raise TestDesignValidationError(
            f"payload must be a JSON object, got {type(raw).__name__}"
        )
    schema_version = raw.get("schema_version")
    if schema_version != DRAFT_SCHEMA_VERSION:
        raise TestDesignValidationError(
            "unsupported schema_version; expected the current draft schema"
        )
    try:
        return TestCoverageDraft(
            draft_id=draft_id,
            workspace_id=_require_str(raw, "workspace_id"),
            conversation_id=_require_str(raw, "conversation_id"),
            source_reference=_decode_reference(raw.get("source_reference")),
            ticket_identifier=_require_str(raw, "ticket_identifier"),
            status=_normalize_stored_status(_require_str(raw, "status")),  # type: ignore[arg-type]
            candidates=tuple(
                _decode_candidate(item)
                for item in _require_list(raw, "candidates")
            ),
            version=version,
        )
    except TestDesignValidationError:
        raise
    except Exception as error:
        raise TestDesignValidationError(
            f"payload could not be decoded as a draft: {error}"
        ) from error


def _encode_candidate(candidate: TestCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "title": candidate.title,
        "category": candidate.category,
        "rationale": candidate.rationale,
        "evidence_references": [
            {"source_type": ref.source_type, "source_id": ref.source_id}
            for ref in candidate.evidence_references
        ],
        "selected": candidate.selected,
        "origin": candidate.origin,
    }


def _decode_candidate(raw: object) -> TestCandidate:
    data = _require_mapping(raw, "candidates item")
    return TestCandidate(
        candidate_id=_require_str(data, "candidate_id"),
        title=_require_str(data, "title"),
        category=_normalize_stored_category(_require_str(data, "category")),  # type: ignore[arg-type]
        rationale=_require_str(data, "rationale"),
        evidence_references=_decode_references(data.get("evidence_references")),
        selected=_require_bool(data, "selected"),
        origin=_require_str(data, "origin"),  # type: ignore[arg-type]
    )


def _decode_references(raw: object) -> tuple[SourceReference, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise TestDesignValidationError(
            "evidence_references must be a list, "
            f"got {type(raw).__name__}"
        )
    return tuple(_decode_reference(item) for item in raw)


def _decode_reference(raw: object) -> SourceReference:
    data = _require_mapping(raw, "source_reference")
    return SourceReference(
        _require_str(data, "source_id"),
        _require_str(data, "source_type"),
    )


def _require_mapping(raw: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise TestDesignValidationError(
            f"{field_name} must be an object, got {type(raw).__name__}"
        )
    return raw


def _require_list(raw: Mapping[str, Any], field_name: str) -> Sequence[Any]:
    value = raw.get(field_name)
    if not isinstance(value, list):
        raise TestDesignValidationError(
            f"{field_name} must be a list, got {type(value).__name__}"
        )
    return value


def _require_str(raw: Mapping[str, Any], field_name: str) -> str:
    value = raw.get(field_name)
    if not isinstance(value, str):
        raise TestDesignValidationError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    return value


def _require_bool(raw: Mapping[str, Any], field_name: str) -> bool:
    value = raw.get(field_name)
    if not isinstance(value, bool):
        raise TestDesignValidationError(
            f"{field_name} must be a bool, got {type(value).__name__}"
        )
    return value
