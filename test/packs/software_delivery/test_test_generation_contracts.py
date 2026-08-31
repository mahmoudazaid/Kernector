"""Unit tests for Software Delivery test-case generation contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from domain.knowledge import SourceReference
from packs.software_delivery.contracts import (
    GeneratedTestCase,
    TestCaseEvidence,
    TestGenerationRequest,
    TestGenerationResult,
)
from packs.software_delivery.errors import (
    RiskScoreValidationError,
    TestCaseGenerationValidationError,
)
from packs.software_delivery.limits import (
    MAX_EVIDENCE_ITEMS,
    MAX_SOURCE_ID_CHARS,
    MAX_TARGET_CHARS,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:cannot collect test class:pytest.PytestCollectionWarning"
)


def _ref(source_id: str = "S-1", source_type: str = "user_story") -> SourceReference:
    return SourceReference(source_id, source_type)


def _evidence(
    source_id: str = "S-1",
    source_type: str = "user_story",
    text: str = "As a user I want login.",
) -> TestCaseEvidence:
    return TestCaseEvidence(_ref(source_id, source_type), text)


def test_request_defaults_output_style_to_steps() -> None:
    request = TestGenerationRequest("Assess auth", [_evidence()])
    assert request.output_style == "steps"


def test_request_accepts_explicit_styles() -> None:
    assert TestGenerationRequest("t", [_evidence()], "steps").output_style == "steps"
    assert (
        TestGenerationRequest("t", [_evidence()], "gherkin").output_style == "gherkin"
    )


def test_request_rejects_unsupported_style() -> None:
    with pytest.raises(TestCaseGenerationValidationError, match="output_style"):
        TestGenerationRequest("t", [_evidence()], "cucumber")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad_style",
    [
        1,
        1.5,
        True,
        None,
        [],
        {},
        ["steps"],
        {"steps": True},
        {"nested": []},
    ],
)
def test_request_rejects_non_string_output_style(bad_style: object) -> None:
    with pytest.raises(TestCaseGenerationValidationError, match="output_style"):
        TestGenerationRequest("t", [_evidence()], bad_style)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_style", ["cucumber", "Cucumber", "STEPS", ""])
def test_request_rejects_unsupported_string_output_style(bad_style: str) -> None:
    with pytest.raises(TestCaseGenerationValidationError, match="output_style"):
        TestGenerationRequest("t", [_evidence()], bad_style)  # type: ignore[arg-type]


def test_request_rejects_blank_target() -> None:
    with pytest.raises(TestCaseGenerationValidationError, match="target"):
        TestGenerationRequest("  ", [_evidence()])


def test_request_rejects_empty_evidence() -> None:
    with pytest.raises(TestCaseGenerationValidationError, match="evidence"):
        TestGenerationRequest("Assess", [])


def test_request_rejects_too_many_evidence_items() -> None:
    items = [_evidence(f"id-{i}", text=f"text {i}") for i in range(MAX_EVIDENCE_ITEMS + 1)]
    with pytest.raises(TestCaseGenerationValidationError, match="at most"):
        TestGenerationRequest("Assess", items)


def test_request_rejects_overlong_target() -> None:
    with pytest.raises(TestCaseGenerationValidationError, match="target"):
        TestGenerationRequest("x" * (MAX_TARGET_CHARS + 1), [_evidence()])


def test_evidence_rejects_overlong_source_id() -> None:
    with pytest.raises(TestCaseGenerationValidationError, match="source_id"):
        TestCaseEvidence(_ref("x" * (MAX_SOURCE_ID_CHARS + 1)), "body")


def test_request_is_immutable() -> None:
    request = TestGenerationRequest("Assess", [_evidence()])
    with pytest.raises(FrozenInstanceError):
        request.target = "other"  # type: ignore[misc]


def test_generated_case_sorts_and_collapses_reference_order() -> None:
    case = GeneratedTestCase(
        "Login",
        ("Open page",),
        "Home visible",
        [_ref("b", "srs"), _ref("a", "code"), _ref("a", "code")],
    )
    assert case.references == (_ref("a", "code"), _ref("b", "srs"))


def test_result_preserves_case_order() -> None:
    cases = [
        GeneratedTestCase("B", ("s",), "e", [_ref("1")]),
        GeneratedTestCase("A", ("s",), "e", [_ref("2")]),
    ]
    result = TestGenerationResult("steps", cases)
    assert [c.title for c in result.test_cases] == ["B", "A"]


def test_risk_helpers_still_raise_risk_score_error() -> None:
    """Regression: risk contracts must not raise test-generation validation."""
    from packs.software_delivery.contracts import RiskAssessmentRequest

    with pytest.raises(RiskScoreValidationError):
        RiskAssessmentRequest("  ", [])
    with pytest.raises(RiskScoreValidationError):
        RiskAssessmentRequest("ok", [])
