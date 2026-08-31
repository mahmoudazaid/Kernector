"""Tool adapter for ``software_delivery.risk_score``."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from domain.errors import DomainValidationError, ToolFailureError
from domain.knowledge import SourceReference
from packs.software_delivery.contracts import (
    RiskAssessmentRequest,
    RiskAssessmentResult,
    RiskEvidence,
)
from packs.software_delivery.errors import RiskScoreValidationError
from packs.software_delivery.scoring import score_risk

TOOL_NAME = "software_delivery.risk_score"
TOOL_DESCRIPTION = (
    "Score software-delivery risk from a multi-source evidence bundle."
)

_ALLOWED_EVIDENCE_KEYS = frozenset(
    {"source_id", "source_type", "text", "is_complete"}
)
_ALLOWED_ROOT_KEYS = frozenset({"target", "evidence"})


class RiskScoreTool:
    """Implements ``domain.ports.Tool`` for Software Delivery risk scoring."""

    def __init__(
        self,
        *,
        scorer: Callable[[RiskAssessmentRequest], RiskAssessmentResult] = score_risk,
    ) -> None:
        self._scorer = scorer

    @property
    def name(self) -> str:
        return TOOL_NAME

    @property
    def description(self) -> str:
        return TOOL_DESCRIPTION

    def run(self, arguments: Mapping[str, object]) -> str:
        """Validate arguments, score risk, and return JSON text.

        Raises:
            RiskScoreValidationError: Invalid or incomplete arguments.
            ToolFailureError: Unexpected failure after valid arguments.
        """
        request = _parse_request(arguments)
        try:
            result = self._scorer(request)
        except RiskScoreValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - map unexpected failures
            raise ToolFailureError("Risk scoring failed") from exc
        return _serialize_result(result)


def _require_nonblank_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RiskScoreValidationError(f"{field_name} must be a non-blank string")
    return value


def _parse_request(arguments: Mapping[str, object]) -> RiskAssessmentRequest:
    if not isinstance(arguments, Mapping):
        raise RiskScoreValidationError(
            f"arguments must be a mapping, got {arguments!r}"
        )
    unknown = set(arguments) - _ALLOWED_ROOT_KEYS
    if unknown:
        raise RiskScoreValidationError(
            f"unknown argument keys: {sorted(unknown)}"
        )
    if "target" not in arguments:
        raise RiskScoreValidationError("target is required")
    if "evidence" not in arguments:
        raise RiskScoreValidationError("evidence is required")

    target = _require_nonblank_str(arguments["target"], "target")
    raw_evidence = arguments["evidence"]
    if isinstance(raw_evidence, (str, bytes)) or not isinstance(
        raw_evidence, Sequence
    ):
        raise RiskScoreValidationError(
            f"evidence must be a sequence, got {raw_evidence!r}"
        )

    evidence: list[RiskEvidence] = []
    for item in raw_evidence:
        evidence.append(_parse_evidence_item(item))
    return RiskAssessmentRequest(target, evidence)


def _parse_evidence_item(item: object) -> RiskEvidence:
    if not isinstance(item, Mapping):
        raise RiskScoreValidationError(
            f"evidence items must be mappings, got {item!r}"
        )
    for key in item:
        if not isinstance(key, str) or not key.strip():
            raise RiskScoreValidationError(
                f"evidence keys must be non-blank strings, got {key!r}"
            )
    unknown = set(item) - _ALLOWED_EVIDENCE_KEYS
    if unknown:
        raise RiskScoreValidationError(
            f"unknown evidence keys: {sorted(unknown)}"
        )
    for required in ("source_id", "source_type", "text"):
        if required not in item:
            raise RiskScoreValidationError(f"{required} is required")

    source_id = _require_nonblank_str(item["source_id"], "source_id")
    source_type = _require_nonblank_str(item["source_type"], "source_type")
    text = _require_nonblank_str(item["text"], "text")
    is_complete = item.get("is_complete", False)
    try:
        reference = SourceReference(source_id, source_type)
    except DomainValidationError as exc:
        raise RiskScoreValidationError(str(exc)) from exc
    return RiskEvidence(reference, text, is_complete=is_complete)  # type: ignore[arg-type]


def _serialize_result(result: RiskAssessmentResult) -> str:
    payload: dict[str, Any] = {
        "score": result.score,
        "level": result.level,
        "factors": [
            {
                "factor_id": factor.factor_id,
                "weight": factor.weight,
                "references": [
                    {
                        "source_id": ref.source_id,
                        "source_type": ref.source_type,
                    }
                    for ref in factor.references
                ],
            }
            for factor in result.factors
        ],
        "rationale": result.rationale,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
