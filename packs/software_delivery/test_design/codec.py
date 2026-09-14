"""Serialize and deserialize test-design drafts for opaque storage."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from domain.knowledge import SourceReference
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.models import (
    COVERAGE_CATEGORIES,
    COVERAGE_CATEGORIES_DISPLAY,
    CoverageGap,
    TestCandidate,
    TestCoverageDraft,
    TestScenario,
)

DRAFT_SCHEMA_VERSION = 1

# Older drafts used a wider category allowlist; map on decode so GET stays loadable.
_LEGACY_CATEGORY_MAP: dict[str, str] = {
    "happy_path": "positive",
    "integration": "positive",
    "permission_security": "negative",
    "failure_recovery": "edge_case",
}


def _normalize_stored_category(raw: str) -> str:
    if raw in COVERAGE_CATEGORIES:
        return raw
    mapped = _LEGACY_CATEGORY_MAP.get(raw)
    if mapped is not None:
        return mapped
    raise TestDesignValidationError(
        f"category must be one of {COVERAGE_CATEGORIES_DISPLAY}"
    )


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
        "scenarios": [_encode_scenario(item) for item in draft.scenarios],
        "coverage_gaps": [
            {"category": gap.category, "detail": gap.detail}
            for gap in draft.coverage_gaps
        ],
    }
    return json.dumps(body, separators=(",", ":"), sort_keys=True)


def decode_draft_payload(
    payload: str,
    *,
    draft_id: str,
    version: int,
) -> TestCoverageDraft:
    """Decode an opaque payload into a typed draft.

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
            f"unsupported schema_version {schema_version!r}; "
            f"expected {DRAFT_SCHEMA_VERSION}"
        )
    try:
        return TestCoverageDraft(
            draft_id=draft_id,
            workspace_id=_require_str(raw, "workspace_id"),
            conversation_id=_require_str(raw, "conversation_id"),
            source_reference=_decode_reference(raw.get("source_reference")),
            ticket_identifier=_require_str(raw, "ticket_identifier"),
            status=_require_str(raw, "status"),  # type: ignore[arg-type]
            candidates=tuple(
                _decode_candidate(item)
                for item in _require_list(raw, "candidates")
            ),
            scenarios=tuple(
                _decode_scenario(item) for item in _require_list(raw, "scenarios")
            ),
            coverage_gaps=tuple(
                _decode_gap(item) for item in _require_list(raw, "coverage_gaps")
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


def _encode_scenario(scenario: TestScenario) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "candidate_id": scenario.candidate_id,
        "title": scenario.title,
        "category": scenario.category,
        "preconditions": list(scenario.preconditions),
        "steps": list(scenario.steps),
        "expected_result": scenario.expected_result,
        "evidence_references": [
            {"source_type": ref.source_type, "source_id": ref.source_id}
            for ref in scenario.evidence_references
        ],
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


def _decode_scenario(raw: object) -> TestScenario:
    data = _require_mapping(raw, "scenarios item")
    return TestScenario(
        scenario_id=_require_str(data, "scenario_id"),
        candidate_id=_require_str(data, "candidate_id"),
        title=_require_str(data, "title"),
        category=_normalize_stored_category(_require_str(data, "category")),  # type: ignore[arg-type]
        preconditions=tuple(_require_str_list(data, "preconditions")),
        steps=tuple(_require_str_list(data, "steps")),
        expected_result=_require_str(data, "expected_result"),
        evidence_references=_decode_references(data.get("evidence_references")),
    )


def _decode_gap(raw: object) -> CoverageGap:
    data = _require_mapping(raw, "coverage_gaps item")
    return CoverageGap(
        category=_normalize_stored_category(_require_str(data, "category")),  # type: ignore[arg-type]
        detail=_require_str(data, "detail"),
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


def _require_list(data: Mapping[str, Any], field_name: str) -> Sequence[Any]:
    value = data.get(field_name)
    if not isinstance(value, list):
        raise TestDesignValidationError(
            f"{field_name} must be a list, got {type(value).__name__}"
        )
    return value


def _require_str_list(data: Mapping[str, Any], field_name: str) -> list[str]:
    items = _require_list(data, field_name)
    result: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise TestDesignValidationError(
                f"{field_name} items must be strings, got {type(item).__name__}"
            )
        result.append(item)
    return result


def _require_str(data: Mapping[str, Any], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str):
        raise TestDesignValidationError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    return value


def _require_bool(data: Mapping[str, Any], field_name: str) -> bool:
    value = data.get(field_name)
    if not isinstance(value, bool):
        raise TestDesignValidationError(
            f"{field_name} must be a bool, got {type(value).__name__}"
        )
    return value
