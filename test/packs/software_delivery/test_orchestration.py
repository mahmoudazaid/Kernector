"""Tests for Software Delivery orchestration chains and typed outcomes."""

from __future__ import annotations

import json

import pytest

from domain.errors import ToolFailureError
from domain.knowledge import SourceReference
from packs.software_delivery.errors import OrchestrationValidationError
from packs.software_delivery.evidence_bundle import (
    EvidenceBundle,
    EvidenceBundleItem,
    evidence_bundle_from_hits,
)
from packs.software_delivery.orchestration import OrchestrateSoftwareDelivery
from packs.software_delivery.orchestration_contracts import (
    ExportMarkdownOutcome,
    GenerateTestsOutcome,
    OrchestrateSoftwareDeliveryRequest,
    RiskScoreOutcome,
)
from packs.software_delivery.orchestration_policy import (
    EXPORT_TEST_CASES_MARKDOWN_TOOL,
    GENERATE_TEST_CASES_TOOL,
    RISK_SCORE_TOOL,
    SoftwareDeliveryIntent,
)
from test.packs.software_delivery.test_evidence_bundle import _hit


class _RecordingInvoke:
    def __init__(self, results: dict[str, str] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._results = dict(results or {})

    def __call__(self, tool_name: str, arguments: dict[str, object]) -> str:
        self.calls.append((tool_name, arguments))
        if tool_name not in self._results:
            raise ToolFailureError(f"missing fake result for {tool_name!r}")
        return self._results[tool_name]


def _bundle() -> EvidenceBundle:
    return evidence_bundle_from_hits([_hit()])


def _risk_json() -> str:
    return json.dumps(
        {
            "score": 40,
            "level": "medium",
            "factors": [
                {
                    "factor_id": "missing_acceptance_criteria",
                    "weight": 10,
                    "references": [
                        {"source_id": "US-1", "source_type": "user_story"}
                    ],
                }
            ],
            "rationale": "Evidence suggests delivery risk.",
        }
    )


def _generate_json() -> str:
    return json.dumps(
        {
            "output_style": "steps",
            "test_cases": [
                {
                    "title": "Login MFA",
                    "steps": ["open login"],
                    "expected": "prompted",
                    "references": [
                        {"source_id": "US-1", "source_type": "user_story"}
                    ],
                }
            ],
        }
    )


def _request(
    intent: SoftwareDeliveryIntent,
) -> OrchestrateSoftwareDeliveryRequest:
    return OrchestrateSoftwareDeliveryRequest(
        intent=intent,
        target="Assess MFA",
        evidence=_bundle(),
    )


def test_risk_score_chain_invokes_only_risk_tool_with_typed_outcome() -> None:
    invoke = _RecordingInvoke({RISK_SCORE_TOOL: _risk_json()})
    response = OrchestrateSoftwareDelivery(invoke).execute(
        _request(SoftwareDeliveryIntent.RISK_SCORE)
    )

    assert [name for name, _ in invoke.calls] == [RISK_SCORE_TOOL]
    outcome = response.outcomes[0]
    assert isinstance(outcome, RiskScoreOutcome)
    assert outcome.assessment.score == 40
    assert outcome.assessment.factors[0].references[0] == SourceReference(
        "US-1", "user_story"
    )


def test_risk_then_generate_chain_order_and_payloads() -> None:
    invoke = _RecordingInvoke(
        {
            RISK_SCORE_TOOL: _risk_json(),
            GENERATE_TEST_CASES_TOOL: _generate_json(),
        }
    )
    response = OrchestrateSoftwareDelivery(invoke).execute(
        _request(SoftwareDeliveryIntent.RISK_SCORE_GENERATE_TESTS)
    )

    assert [name for name, _ in invoke.calls] == [
        RISK_SCORE_TOOL,
        GENERATE_TEST_CASES_TOOL,
    ]
    assert "is_complete" in invoke.calls[0][1]["evidence"][0]
    assert "is_complete" not in invoke.calls[1][1]["evidence"][0]
    assert isinstance(response.outcomes[0], RiskScoreOutcome)
    assert isinstance(response.outcomes[1], GenerateTestsOutcome)
    assert response.outcomes[1].result.test_cases[0].references[0].source_id == "US-1"


def test_full_chain_preserves_provenance_in_markdown() -> None:
    invoke = _RecordingInvoke(
        {
            RISK_SCORE_TOOL: _risk_json(),
            GENERATE_TEST_CASES_TOOL: _generate_json(),
            EXPORT_TEST_CASES_MARKDOWN_TOOL: "# Test Cases\n\n- `US-1` (user_story)\n",
        }
    )
    response = OrchestrateSoftwareDelivery(invoke).execute(
        _request(SoftwareDeliveryIntent.RISK_SCORE_GENERATE_EXPORT)
    )

    assert [name for name, _ in invoke.calls] == [
        RISK_SCORE_TOOL,
        GENERATE_TEST_CASES_TOOL,
        EXPORT_TEST_CASES_MARKDOWN_TOOL,
    ]
    export_args = invoke.calls[2][1]
    assert export_args["test_cases"][0]["references"][0]["source_id"] == "US-1"
    export_outcome = response.outcomes[2]
    assert isinstance(export_outcome, ExportMarkdownOutcome)
    assert "US-1" in export_outcome.markdown


def test_failure_short_circuits_before_later_tools() -> None:
    class _FailAfterRisk(_RecordingInvoke):
        def __call__(self, tool_name: str, arguments: dict[str, object]) -> str:
            self.calls.append((tool_name, arguments))
            if tool_name == GENERATE_TEST_CASES_TOOL:
                raise ToolFailureError("generate failed")
            if tool_name not in self._results:
                raise ToolFailureError(f"missing fake result for {tool_name!r}")
            return self._results[tool_name]

    invoke = _FailAfterRisk(
        {
            RISK_SCORE_TOOL: _risk_json(),
            GENERATE_TEST_CASES_TOOL: _generate_json(),
        }
    )

    with pytest.raises(ToolFailureError, match="generate failed"):
        OrchestrateSoftwareDelivery(invoke).execute(
            _request(SoftwareDeliveryIntent.RISK_SCORE_GENERATE_EXPORT)
        )

    assert [name for name, _ in invoke.calls] == [
        RISK_SCORE_TOOL,
        GENERATE_TEST_CASES_TOOL,
    ]
    assert EXPORT_TEST_CASES_MARKDOWN_TOOL not in [name for name, _ in invoke.calls]


def test_invalid_risk_json_fails_before_generate() -> None:
    invoke = _RecordingInvoke({RISK_SCORE_TOOL: "not-json"})

    with pytest.raises(ToolFailureError, match="valid JSON"):
        OrchestrateSoftwareDelivery(invoke).execute(
            _request(SoftwareDeliveryIntent.RISK_SCORE_GENERATE_TESTS)
        )

    assert len(invoke.calls) == 1
    assert invoke.calls[0][0] == RISK_SCORE_TOOL


def test_empty_evidence_bundle_rejected_at_construction_before_invoke() -> None:
    invoke = _RecordingInvoke()

    with pytest.raises(OrchestrationValidationError, match="items must be non-empty"):
        EvidenceBundle(items=())

    assert invoke.calls == []


def test_malformed_evidence_item_rejected_without_attribute_error() -> None:
    invoke = _RecordingInvoke()

    with pytest.raises(OrchestrationValidationError, match="reference must be"):
        EvidenceBundleItem("not-a-reference", "text")  # type: ignore[arg-type]

    with pytest.raises(OrchestrationValidationError, match="text must be non-empty"):
        EvidenceBundleItem(SourceReference("US-1", "user_story"), "   ")

    with pytest.raises(OrchestrationValidationError, match="is_complete must be a bool"):
        EvidenceBundleItem(
            SourceReference("US-1", "user_story"),
            "text",
            is_complete=1,  # type: ignore[arg-type]
        )

    assert invoke.calls == []


def test_malformed_evidence_bundle_rejected_before_invoke_without_attribute_error() -> None:
    invoke = _RecordingInvoke()

    with pytest.raises(OrchestrationValidationError, match="items must be a sequence"):
        EvidenceBundle(items="not-a-sequence")  # type: ignore[arg-type]

    with pytest.raises(OrchestrationValidationError, match="items entries must be"):
        EvidenceBundle(items=[{"source_id": "US-1"}])  # type: ignore[list-item]

    with pytest.raises(OrchestrationValidationError, match="items must be non-empty"):
        OrchestrateSoftwareDeliveryRequest(
            intent=SoftwareDeliveryIntent.RISK_SCORE,
            target="Assess MFA",
            evidence=EvidenceBundle(items=()),
        )

    assert invoke.calls == []
