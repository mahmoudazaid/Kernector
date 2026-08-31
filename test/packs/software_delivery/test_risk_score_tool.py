"""Tests for the software_delivery.risk_score tool adapter."""

import json

import pytest

from domain.errors import ToolFailureError
from packs.software_delivery.contracts import RiskAssessmentResult
from packs.software_delivery.errors import RiskScoreValidationError
from packs.software_delivery.risk_score_tool import TOOL_NAME, RiskScoreTool


def _valid_arguments() -> dict[str, object]:
    return {
        "target": "Assess authentication release risk",
        "evidence": [
            {
                "source_id": "SRS-12",
                "source_type": "srs",
                "text": "Authentication requirements remain TBD.",
                "is_complete": True,
            },
            {
                "source_id": "tests/auth-login",
                "source_type": "test",
                "text": "Critical login regression is failing.",
                "is_complete": False,
            },
        ],
    }


def test_tool_name_and_description() -> None:
    tool = RiskScoreTool()
    assert tool.name == TOOL_NAME == "software_delivery.risk_score"
    assert tool.description.strip()


def test_valid_multi_source_arguments_return_semantic_json() -> None:
    payload = json.loads(RiskScoreTool().run(_valid_arguments()))
    assert payload["score"] == 15 + 20 + 15 + 10
    assert payload["level"] == "high"
    factor_ids = [f["factor_id"] for f in payload["factors"]]
    assert factor_ids == [
        "ambiguous_language",
        "high_severity",
        "known_defect_or_failure",
        "security_sensitive",
    ]
    ambiguous = next(f for f in payload["factors"] if f["factor_id"] == "ambiguous_language")
    assert ambiguous["references"] == [
        {"source_id": "SRS-12", "source_type": "srs"}
    ]
    assert isinstance(payload["rationale"], str) and payload["rationale"].strip()


def test_unknown_root_key_fails_before_scoring() -> None:
    calls: list[object] = []

    def boom(request: object) -> RiskAssessmentResult:
        calls.append(request)
        raise AssertionError("scorer must not run")

    args = _valid_arguments()
    args["extra"] = "nope"
    with pytest.raises(RiskScoreValidationError, match="unknown"):
        RiskScoreTool(scorer=boom).run(args)
    assert calls == []


def test_malformed_evidence_fails_before_scoring() -> None:
    calls: list[object] = []

    def boom(request: object) -> RiskAssessmentResult:
        calls.append(request)
        raise AssertionError("scorer must not run")

    with pytest.raises(RiskScoreValidationError):
        RiskScoreTool(scorer=boom).run(
            {"target": "Assess", "evidence": ["not-a-mapping"]}
        )
    assert calls == []


def test_references_round_trip_in_factors() -> None:
    payload = json.loads(
        RiskScoreTool().run(
            {
                "target": "Assess",
                "evidence": [
                    {
                        "source_id": "O-1",
                        "source_type": "openapi",
                        "text": "Requires OAuth security.",
                        "is_complete": True,
                    }
                ],
            }
        )
    )
    assert payload["factors"][0]["references"] == [
        {"source_id": "O-1", "source_type": "openapi"}
    ]


def test_unexpected_scorer_failure_maps_to_tool_failure_error() -> None:
    def boom(_request: object) -> RiskAssessmentResult:
        raise RuntimeError("internal detail with secret-token")

    with pytest.raises(ToolFailureError, match="Risk scoring failed") as raised:
        RiskScoreTool(scorer=boom).run(_valid_arguments())
    assert "secret-token" not in str(raised.value)
    assert raised.value.__cause__ is not None
