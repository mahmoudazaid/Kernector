"""Deterministic scoring policy tests for Software Delivery risk scoring."""

import pytest

from domain.knowledge import SourceReference
from packs.software_delivery.contracts import (
    RiskAssessmentRequest,
    RiskEvidence,
)
from packs.software_delivery.errors import RiskScoreValidationError
from packs.software_delivery.scoring import risk_level, score_risk


def _ref(source_id: str, source_type: str) -> SourceReference:
    return SourceReference(source_id, source_type)


def _item(
    source_id: str,
    source_type: str,
    text: str,
    *,
    is_complete: bool = True,
) -> RiskEvidence:
    return RiskEvidence(_ref(source_id, source_type), text, is_complete=is_complete)


def _request(*evidence: RiskEvidence, target: str = "Assess release risk"):
    return RiskAssessmentRequest(target, list(evidence))


@pytest.mark.parametrize(
    "score,level",
    [
        (0, "low"),
        (24, "low"),
        (25, "medium"),
        (49, "medium"),
        (50, "high"),
        (74, "high"),
        (75, "critical"),
        (100, "critical"),
    ],
)
def test_risk_level_boundaries(score: int, level: str) -> None:
    assert risk_level(score) == level


@pytest.mark.parametrize("bad", [-1, 101, True, 12.5, "10"])
def test_risk_level_rejects_invalid_score(bad: object) -> None:
    with pytest.raises(RiskScoreValidationError, match="score"):
        risk_level(bad)


def test_empty_signals_yield_low_zero() -> None:
    result = score_risk(
        _request(
            _item(
                "S-1",
                "user_story",
                "As a user I want login. Acceptance: Given login when submit then ok.",
            )
        )
    )
    assert result.score == 0
    assert result.level == "low"
    assert result.factors == ()
    assert "no elevated signals" in result.rationale.lower()


def test_complete_story_without_ac_is_medium() -> None:
    result = score_risk(
        _request(_item("S-1", "user_story", "As a user I want faster checkout."))
    )
    assert result.score == 25
    assert result.level == "medium"
    assert [f.factor_id for f in result.factors] == ["missing_acceptance_criteria"]
    assert result.factors[0].references == (_ref("S-1", "user_story"),)


def test_incomplete_story_chunk_without_ac_skips_absence_rule() -> None:
    result = score_risk(
        _request(
            _item(
                "S-1",
                "user_story",
                "As a user I want faster checkout.",
                is_complete=False,
            )
        )
    )
    assert "missing_acceptance_criteria" not in {
        f.factor_id for f in result.factors
    }


@pytest.mark.parametrize("source_type", ["openapi", "code", "srs", "test", "confluence"])
def test_non_story_without_ac_skips_absence_rule(source_type: str) -> None:
    result = score_risk(
        _request(_item("X-1", source_type, "Describe checkout behaviour."))
    )
    assert "missing_acceptance_criteria" not in {
        f.factor_id for f in result.factors
    }


def test_common_signals_independent_of_source_kind() -> None:
    result = score_risk(
        _request(
            _item("API-1", "openapi", "OAuth security scheme required."),
            _item("SRS-1", "srs", "Timeout behaviour remains TBD."),
            _item(
                "T-1",
                "test",
                "Critical login regression is failing.",
            ),
        )
    )
    ids = {f.factor_id: f for f in result.factors}
    assert set(ids) == {
        "security_sensitive",
        "ambiguous_language",
        "known_defect_or_failure",
        "high_severity",
    }
    assert ids["security_sensitive"].references == (_ref("API-1", "openapi"),)
    assert ids["ambiguous_language"].references == (_ref("SRS-1", "srs"),)
    assert ids["known_defect_or_failure"].references == (_ref("T-1", "test"),)
    assert ids["high_severity"].references == (_ref("T-1", "test"),)
    assert result.score == 15 + 20 + 15 + 10
    assert result.level == "high"


def test_same_factor_across_sources_counts_weight_once() -> None:
    result = score_risk(
        _request(
            _item(
                "S-1",
                "story",
                "Blocked by billing vendor. Acceptance: Given vendor when called then billed.",
            ),
            _item("C-1", "confluence", "Depends on billing vendor."),
        )
    )
    factor = next(f for f in result.factors if f.factor_id == "external_dependency")
    assert factor.weight == 20
    assert factor.references == (
        _ref("C-1", "confluence"),
        _ref("S-1", "story"),
    )
    assert result.score == 20
    assert [f.factor_id for f in result.factors] == ["external_dependency"]


def test_unknown_source_kind_uses_common_policy() -> None:
    result = score_risk(
        _request(
            _item("Z-1", "future-connector", "Depends on inventory service.")
        )
    )
    assert [f.factor_id for f in result.factors] == ["external_dependency"]
    assert result.score == 20


def test_score_caps_at_one_hundred() -> None:
    result = score_risk(
        _request(
            _item(
                "S-1",
                "user_story",
                "Checkout rewrite. TBD. Blocked by vendor. "
                "Security OAuth. Schema change migration. "
                "Known defect. High severity defect.",
            ),
            _item(
                "T-1",
                "test",
                "Failing test regression with high severity.",
            ),
        )
    )
    assert result.score == 100
    assert result.level == "critical"
    assert len(result.factors) == 7


@pytest.mark.parametrize(
    "text,absent_factor",
    [
        ("There is no external dependency on vendors.", "external_dependency"),
        ("This change is not security-sensitive.", "security_sensitive"),
        ("Ship without data migration this sprint.", "data_or_migration"),
        ("There are no known defects in staging.", "known_defect_or_failure"),
    ],
)
def test_documented_negations_suppress_factors(
    text: str, absent_factor: str
) -> None:
    result = score_risk(_request(_item("N-1", "confluence", text)))
    assert absent_factor not in {f.factor_id for f in result.factors}


def test_high_severity_does_not_combine_across_items() -> None:
    result = score_risk(
        _request(
            _item("A-1", "srs", "Document the severity field carefully."),
            _item("B-1", "test", "Priority is high for triage."),
        )
    )
    assert "high_severity" not in {f.factor_id for f in result.factors}


def test_input_order_does_not_change_result() -> None:
    a = _item("S-1", "story", "Blocked by payments. TBD.")
    b = _item("O-1", "openapi", "OAuth security required.")
    first = score_risk(_request(a, b))
    second = score_risk(_request(b, a))
    assert first == second


def test_repeated_reference_chunks_contribute_with_deduped_factor_refs() -> None:
    """Two chunks from one document both score; factor refs stay unique and stable."""
    chunk_a = _item(
        "DOC-1",
        "confluence",
        "Blocked by payments vendor.",
        is_complete=False,
    )
    chunk_b = _item(
        "DOC-1",
        "confluence",
        "Authentication OAuth remains TBD.",
        is_complete=False,
    )
    first = score_risk(_request(chunk_a, chunk_b))
    second = score_risk(_request(chunk_b, chunk_a))
    assert first == second
    ids = {f.factor_id: f for f in first.factors}
    assert set(ids) == {
        "ambiguous_language",
        "external_dependency",
        "security_sensitive",
    }
    assert first.score == 15 + 20 + 20
    for factor in first.factors:
        assert factor.references == (_ref("DOC-1", "confluence"),)


def test_identical_requests_are_stable() -> None:
    request = _request(
        _item("S-1", "user_story", "As a user I want login without acceptance.")
    )
    assert score_risk(request) == score_risk(request)
