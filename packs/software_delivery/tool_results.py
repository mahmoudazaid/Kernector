"""Deserialize opaque tool JSON into pack-local typed outcomes."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from domain.errors import ToolFailureError
from domain.knowledge import SourceReference
from packs.software_delivery.contracts import (
    GeneratedTestCase,
    RiskAssessmentResult,
    RiskFactor,
    TestCaseStyle,
    TestGenerationResult,
)


def parse_risk_assessment_result(payload: str) -> RiskAssessmentResult:
    """Parse ``software_delivery.risk_score`` JSON into a typed result.

    Raises:
        ToolFailureError: Payload is invalid or incomplete.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ToolFailureError("Risk score result was not valid JSON") from exc
    if not isinstance(data, Mapping):
        raise ToolFailureError("Risk score result must be a JSON object")
    try:
        factors = _parse_risk_factors(data.get("factors"))
        return RiskAssessmentResult(
            score=data["score"],  # type: ignore[arg-type]
            level=data["level"],  # type: ignore[arg-type]
            factors=factors,
            rationale=data["rationale"],  # type: ignore[arg-type]
        )
    except (KeyError, TypeError, ValueError, Exception) as exc:
        if isinstance(exc, ToolFailureError):
            raise
        raise ToolFailureError("Risk score result missing required fields") from exc


def parse_test_generation_result(payload: str) -> TestGenerationResult:
    """Parse ``software_delivery.generate_test_cases`` JSON into a typed result.

    Raises:
        ToolFailureError: Payload is invalid or incomplete.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ToolFailureError(
            "Generate test cases result was not valid JSON"
        ) from exc
    if not isinstance(data, Mapping):
        raise ToolFailureError("Generate test cases result must be a JSON object")
    try:
        style: TestCaseStyle = data["output_style"]  # type: ignore[assignment]
        cases = _parse_generated_cases(data.get("test_cases"))
        return TestGenerationResult(style, cases)
    except (KeyError, TypeError, ValueError, Exception) as exc:
        if isinstance(exc, ToolFailureError):
            raise
        raise ToolFailureError(
            "Generate test cases result missing required fields"
        ) from exc


def _parse_risk_factors(raw: object) -> tuple[RiskFactor, ...]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ValueError("factors must be a sequence")
    factors: list[RiskFactor] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("factor must be a mapping")
        references = _parse_references(item.get("references"))
        factors.append(
            RiskFactor(
                factor_id=item["factor_id"],  # type: ignore[arg-type]
                weight=item["weight"],  # type: ignore[arg-type]
                references=references,
            )
        )
    return tuple(factors)


def _parse_generated_cases(raw: object) -> tuple[GeneratedTestCase, ...]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ValueError("test_cases must be a sequence")
    cases: list[GeneratedTestCase] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("test case must be a mapping")
        references = _parse_references(item.get("references"))
        steps_raw = item.get("steps")
        if isinstance(steps_raw, (str, bytes)) or not isinstance(steps_raw, Sequence):
            raise ValueError("steps must be a sequence")
        cases.append(
            GeneratedTestCase(
                title=item["title"],  # type: ignore[arg-type]
                steps=tuple(steps_raw),
                expected=item["expected"],  # type: ignore[arg-type]
                references=references,
            )
        )
    return tuple(cases)


def _parse_references(raw: object) -> tuple[SourceReference, ...]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ValueError("references must be a sequence")
    refs: list[SourceReference] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("reference must be a mapping")
        refs.append(
            SourceReference(
                item["source_id"],  # type: ignore[arg-type]
                item["source_type"],  # type: ignore[arg-type]
            )
        )
    return tuple(refs)


def serialize_test_generation_for_export(result: TestGenerationResult) -> dict[str, Any]:
    """Project a typed generation result into export-tool argument fields."""
    return {
        "output_style": result.output_style,
        "test_cases": [
            {
                "title": case.title,
                "steps": list(case.steps),
                "expected": case.expected,
                "references": [
                    {
                        "source_id": ref.source_id,
                        "source_type": ref.source_type,
                    }
                    for ref in case.references
                ],
            }
            for case in result.test_cases
        ],
    }
