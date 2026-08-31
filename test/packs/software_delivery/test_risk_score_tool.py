"""Tests for the software_delivery.risk_score tool adapter."""

import json

import pytest

from domain.errors import DomainValidationError, ToolArgumentValidationError, ToolFailureError
import packs.software_delivery.risk_score_tool as risk_score_tool_module
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
    ambiguous = next(
        f for f in payload["factors"] if f["factor_id"] == "ambiguous_language"
    )
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


def test_mixed_invalid_and_unknown_evidence_keys_fail_before_scoring() -> None:
    calls: list[object] = []

    def boom(request: object) -> RiskAssessmentResult:
        calls.append(request)
        raise AssertionError("scorer must not run")

    with pytest.raises(RiskScoreValidationError) as raised:
        RiskScoreTool(scorer=boom).run(
            {
                "target": "Assess",
                "evidence": [
                    {
                        7: "invalid",
                        "extra": "unknown",
                        "source_id": "doc-1",
                        "source_type": "document",
                        "text": "evidence",
                    }
                ],
            }
        )
    assert not isinstance(raised.value, TypeError)
    assert calls == []


@pytest.mark.parametrize("bad_key", [7, True, ("a",), "", "   ", "\n"])
def test_non_string_or_blank_evidence_keys_fail_before_scoring(
    bad_key: object,
) -> None:
    calls: list[object] = []

    def boom(request: object) -> RiskAssessmentResult:
        calls.append(request)
        raise AssertionError("scorer must not run")

    with pytest.raises(RiskScoreValidationError):
        RiskScoreTool(scorer=boom).run(
            {
                "target": "Assess",
                "evidence": [
                    {
                        bad_key: "x",
                        "source_id": "doc-1",
                        "source_type": "document",
                        "text": "evidence",
                    }
                ],
            }
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


_INVALID_SCALARS = [None, 1, True, False, 3.14, ["x"], {"k": "v"}]
_BLANK_STRINGS = ["", "   ", "\n"]


def _scorer_spy() -> tuple[list[object], object]:
    calls: list[object] = []

    def boom(request: object) -> RiskAssessmentResult:
        calls.append(request)
        raise AssertionError("scorer must not run")

    return calls, boom


@pytest.mark.parametrize("bad", _INVALID_SCALARS + _BLANK_STRINGS)
def test_non_string_or_blank_target_fails_before_scoring(bad: object) -> None:
    calls, boom = _scorer_spy()
    args = _valid_arguments()
    args["target"] = bad
    with pytest.raises(RiskScoreValidationError) as raised:
        RiskScoreTool(scorer=boom).run(args)
    assert isinstance(raised.value, ToolArgumentValidationError)
    assert calls == []


@pytest.mark.parametrize("field", ["source_id", "source_type", "text"])
@pytest.mark.parametrize("bad", _INVALID_SCALARS + _BLANK_STRINGS)
def test_non_string_or_blank_evidence_scalars_fail_before_scoring(
    field: str, bad: object
) -> None:
    calls, boom = _scorer_spy()
    args = _valid_arguments()
    evidence_item = args["evidence"][0]
    assert isinstance(evidence_item, dict)
    item = dict(evidence_item)
    item[field] = bad
    args["evidence"] = [item]
    with pytest.raises(RiskScoreValidationError) as raised:
        RiskScoreTool(scorer=boom).run(args)
    assert isinstance(raised.value, ToolArgumentValidationError)
    assert calls == []


def test_source_reference_domain_validation_is_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def boom(request: object) -> RiskAssessmentResult:
        calls.append(request)
        raise AssertionError("scorer must not run")

    def _raising_reference(source_id: object, source_type: object):
        raise DomainValidationError("source_id must be non-empty")

    monkeypatch.setattr(risk_score_tool_module, "SourceReference", _raising_reference)
    with pytest.raises(RiskScoreValidationError) as raised:
        RiskScoreTool(scorer=boom).run(_valid_arguments())
    assert isinstance(raised.value.__cause__, DomainValidationError)
    assert calls == []
