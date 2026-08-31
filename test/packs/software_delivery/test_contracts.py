"""Unit tests for Software Delivery risk assessment contracts."""

from dataclasses import FrozenInstanceError

import pytest

from domain.knowledge import SourceReference
from packs.software_delivery.contracts import (
    RiskAssessmentRequest,
    RiskAssessmentResult,
    RiskEvidence,
    RiskFactor,
)
from packs.software_delivery.errors import RiskScoreValidationError

BLANK = ["", "   ", "\n"]


def _ref(source_id: str = "S-1", source_type: str = "user_story") -> SourceReference:
    return SourceReference(source_id, source_type)


def _evidence(
    source_id: str = "S-1",
    source_type: str = "user_story",
    text: str = "As a user I want login.",
    *,
    is_complete: bool = True,
) -> RiskEvidence:
    return RiskEvidence(_ref(source_id, source_type), text, is_complete=is_complete)


def test_risk_evidence_reuses_source_reference() -> None:
    reference = _ref()
    evidence = RiskEvidence(reference, "body text", is_complete=True)
    assert evidence.reference is reference
    assert evidence.text == "body text"
    assert evidence.is_complete is True


def test_risk_assessment_request_copies_evidence_to_tuple() -> None:
    items = [_evidence("a"), _evidence("b", "srs")]
    request = RiskAssessmentRequest("Assess auth", items)
    assert request.evidence == tuple(items)
    assert isinstance(request.evidence, tuple)


def test_risk_assessment_request_allows_repeated_references() -> None:
    """Retrieval may return several chunks from one document."""
    chunk_a = _evidence("S-1", "user_story", "Chunk one without acceptance.")
    chunk_b = _evidence("S-1", "user_story", "Chunk two also without acceptance.")
    request = RiskAssessmentRequest("Assess auth", [chunk_a, chunk_b])
    assert request.evidence == (chunk_a, chunk_b)
    assert isinstance(request.evidence, tuple)
    assert request.evidence[0].reference == request.evidence[1].reference


def test_risk_assessment_request_is_immutable() -> None:
    request = RiskAssessmentRequest("Assess auth", [_evidence()])
    with pytest.raises(FrozenInstanceError):
        request.target = "other"  # type: ignore[misc]


@pytest.mark.parametrize("blank", BLANK)
def test_risk_assessment_request_rejects_blank_target(blank: str) -> None:
    with pytest.raises(RiskScoreValidationError, match="target"):
        RiskAssessmentRequest(blank, [_evidence()])


def test_risk_assessment_request_rejects_empty_evidence() -> None:
    with pytest.raises(RiskScoreValidationError, match="evidence"):
        RiskAssessmentRequest("Assess auth", [])


def test_risk_assessment_request_rejects_bare_string_evidence() -> None:
    with pytest.raises(RiskScoreValidationError, match="evidence"):
        RiskAssessmentRequest("Assess auth", "not-a-sequence")  # type: ignore[arg-type]


def test_risk_evidence_rejects_blank_text() -> None:
    with pytest.raises(RiskScoreValidationError, match="text"):
        RiskEvidence(_ref(), "   ")


def test_risk_evidence_rejects_non_bool_is_complete() -> None:
    with pytest.raises(RiskScoreValidationError, match="is_complete"):
        RiskEvidence(_ref(), "body", is_complete=1)  # type: ignore[arg-type]


def test_risk_evidence_rejects_invalid_reference_type() -> None:
    with pytest.raises(RiskScoreValidationError, match="reference"):
        RiskEvidence("not-a-ref", "body")  # type: ignore[arg-type]


def test_risk_factor_copies_and_sorts_references() -> None:
    refs = [_ref("b", "srs"), _ref("a", "code"), _ref("a", "confluence")]
    factor = RiskFactor("ambiguous_language", 15, refs)
    assert factor.references == (
        _ref("a", "code"),
        _ref("a", "confluence"),
        _ref("b", "srs"),
    )


def test_risk_factor_rejects_blank_id() -> None:
    with pytest.raises(RiskScoreValidationError, match="factor_id"):
        RiskFactor("  ", 15, [_ref()])


def test_risk_factor_rejects_non_positive_weight() -> None:
    with pytest.raises(RiskScoreValidationError, match="weight"):
        RiskFactor("ambiguous_language", 0, [_ref()])


def test_risk_factor_rejects_bool_weight() -> None:
    with pytest.raises(RiskScoreValidationError, match="weight"):
        RiskFactor("ambiguous_language", True, [_ref()])  # type: ignore[arg-type]


def test_risk_factor_rejects_empty_references() -> None:
    with pytest.raises(RiskScoreValidationError, match="references"):
        RiskFactor("ambiguous_language", 15, [])


def test_risk_assessment_result_sorts_unique_factors() -> None:
    factors = [
        RiskFactor("security_sensitive", 20, [_ref("s1", "openapi")]),
        RiskFactor("ambiguous_language", 15, [_ref("s2", "srs")]),
    ]
    result = RiskAssessmentResult(35, "medium", factors, "Risk score 35 (medium).")
    assert [f.factor_id for f in result.factors] == [
        "ambiguous_language",
        "security_sensitive",
    ]


def test_risk_assessment_result_rejects_duplicate_factor_ids() -> None:
    factors = [
        RiskFactor("ambiguous_language", 15, [_ref("a")]),
        RiskFactor("ambiguous_language", 15, [_ref("b")]),
    ]
    with pytest.raises(RiskScoreValidationError, match="factor_id"):
        RiskAssessmentResult(15, "low", factors, "dup")


@pytest.mark.parametrize(
    "score,level",
    [
        (-1, "low"),
        (101, "low"),
        (True, "low"),
        (50, "urgent"),
        (50, ""),
    ],
)
def test_risk_assessment_result_rejects_invalid_score_or_level(
    score: object, level: object
) -> None:
    with pytest.raises(RiskScoreValidationError):
        RiskAssessmentResult(
            score,  # type: ignore[arg-type]
            level,  # type: ignore[arg-type]
            [RiskFactor("ambiguous_language", 15, [_ref()])],
            "rationale",
        )


def test_risk_assessment_result_rejects_blank_rationale() -> None:
    with pytest.raises(RiskScoreValidationError, match="rationale"):
        RiskAssessmentResult(
            0,
            "low",
            (),
            "   ",
        )


def test_risk_assessment_result_allows_empty_factors_at_zero() -> None:
    result = RiskAssessmentResult(
        0, "low", (), "No elevated signals were detected in the supplied evidence."
    )
    assert result.factors == ()
    assert result.score == 0
