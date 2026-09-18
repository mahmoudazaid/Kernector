"""TurnRouter: pack-neutral pre-retrieval routing decisions."""

from __future__ import annotations

import pytest

from application.errors import ApplicationValidationError
from application.turn_routing import (
    CONFIDENCE_CONFLICT_OR_MIXED,
    CONFIDENCE_DEFAULT_GROUNDED,
    CONFIDENCE_GENERAL,
    CONFIDENCE_INCOMPLETE,
    CONFIDENCE_READY,
    RoutingKind,
    RoutingDecision,
    TurnRouter,
    WorkflowReadiness,
    WorkflowSignalResult,
    classify_turn,
)
from domain.models import Message


def _ready(hint: str = "drive_export"):
    result = WorkflowSignalResult(
        workflow_hint=hint,
        readiness=WorkflowReadiness.READY,
        reason="workflow_ready",
    )
    return lambda request: result


def _incomplete(
    hint: str = "drive_export",
    *,
    reason: str = "incomplete_workflow",
    missing_fields: tuple[str, ...] = ("selected_titles",),
):
    result = WorkflowSignalResult(
        workflow_hint=hint,
        readiness=WorkflowReadiness.INCOMPLETE,
        reason=reason,
        missing_fields=missing_fields,
        clarification_context={"workflow_hint": hint, "missing_fields": missing_fields},
    )
    return lambda request: result


def test_exactly_one_ready_signal_routes_to_tool_workflow() -> None:
    decision = classify_turn("export to google drive", signals=(_ready(),))
    assert decision == RoutingDecision(
        kind=RoutingKind.TOOL_WORKFLOW,
        routing_confidence=CONFIDENCE_READY,
        ambiguous=False,
        reason="workflow_ready",
        workflow_hint="drive_export",
    )


def test_incomplete_signal_routes_to_clarification_never_rag() -> None:
    decision = classify_turn("export", signals=(_incomplete(),))
    assert decision.kind == RoutingKind.CLARIFICATION
    assert decision.routing_confidence == CONFIDENCE_INCOMPLETE
    assert decision.ambiguous is False
    assert decision.reason == "incomplete_workflow"
    assert decision.workflow_hint == "drive_export"
    assert decision.clarification_context is not None


def test_conflicting_workflow_signals_always_clarify() -> None:
    decision = classify_turn(
        "design tests and export to drive",
        signals=(
            _ready("test_design"),
            _incomplete("drive_export"),
        ),
    )
    assert decision.kind == RoutingKind.CLARIFICATION
    assert decision.ambiguous is True
    assert decision.reason == "conflicting_workflows"
    assert decision.routing_confidence == CONFIDENCE_CONFLICT_OR_MIXED
    assert decision.workflow_hint is None


def test_two_ready_distinct_workflows_conflict() -> None:
    decision = classify_turn(
        "both",
        signals=(_ready("test_design"), _ready("drive_export")),
    )
    assert decision.kind == RoutingKind.CLARIFICATION
    assert decision.reason == "conflicting_workflows"
    assert decision.ambiguous is True


def test_tool_unavailable_is_incomplete_not_rag() -> None:
    result = WorkflowSignalResult(
        workflow_hint="drive_export",
        readiness=WorkflowReadiness.INCOMPLETE,
        reason="tool_unavailable",
        missing_fields=(),
    )
    decision = classify_turn(
        "export to google drive",
        signals=(lambda request: result,),
    )
    assert decision.kind == RoutingKind.CLARIFICATION
    assert decision.reason == "tool_unavailable"
    assert decision.routing_confidence == CONFIDENCE_INCOMPLETE


def test_project_cues_route_to_grounded_answer() -> None:
    decision = classify_turn("What do the docs say about auth in this repo?")
    assert decision.kind == RoutingKind.GROUNDED_ANSWER
    assert decision.reason == "project_cues"
    assert decision.routing_confidence == CONFIDENCE_DEFAULT_GROUNDED


def test_clear_general_cues_route_to_general_answer() -> None:
    decision = classify_turn("Brainstorm three creative taglines for a coffee brand")
    assert decision.kind == RoutingKind.GENERAL_ANSWER
    assert decision.reason == "general_cues"
    assert decision.routing_confidence == CONFIDENCE_GENERAL


def test_mixed_general_and_project_cues_clarify() -> None:
    decision = classify_turn(
        "Brainstorm ideas based on what our repository docs say about auth"
    )
    assert decision.kind == RoutingKind.CLARIFICATION
    assert decision.reason == "mixed_cues"
    assert decision.ambiguous is True
    assert decision.routing_confidence == CONFIDENCE_CONFLICT_OR_MIXED


def test_default_without_cues_is_grounded() -> None:
    decision = classify_turn("Hello there")
    assert decision.kind == RoutingKind.GROUNDED_ANSWER
    assert decision.reason == "default_grounded"


def test_bare_yes_with_raw_history_does_not_promote_to_tool_workflow() -> None:
    history = (
        Message(role="user", content="export"),
        Message(
            role="assistant",
            content="Did you mean export selected titles to Google Drive?",
        ),
    )
    decision = classify_turn("yes", history=history)
    assert decision.kind != RoutingKind.TOOL_WORKFLOW


def test_structured_prior_context_plus_new_fields_can_become_tool_workflow() -> None:
    prior = {
        "workflow_hint": "test_design",
        "missing_fields": ("issue_locator",),
    }
    decision = classify_turn(
        "Design tests for acme/api#42",
        clarification_context=prior,
        signals=(
            _ready("test_design"),
        ),
    )
    assert decision.kind == RoutingKind.TOOL_WORKFLOW
    assert decision.workflow_hint == "test_design"


def test_structured_prior_context_with_bare_yes_stays_clarification() -> None:
    prior = {
        "workflow_hint": "test_design",
        "missing_fields": ("issue_locator",),
    }
    # No signal becomes ready from "yes" alone — signal still incomplete.
    decision = classify_turn(
        "yes",
        clarification_context=prior,
        signals=(
            _incomplete(
                "test_design",
                reason="missing_fields",
                missing_fields=("issue_locator",),
            ),
        ),
    )
    assert decision.kind == RoutingKind.CLARIFICATION
    assert decision.reason == "missing_fields"


def test_turn_router_class_matches_classify_turn() -> None:
    router = TurnRouter()
    assert router.classify("Hello there") == classify_turn("Hello there")


def test_routing_decision_rejects_unknown_reason() -> None:
    with pytest.raises(ApplicationValidationError, match="reason"):
        RoutingDecision(
            kind=RoutingKind.GROUNDED_ANSWER,
            routing_confidence=0.6,
            ambiguous=False,
            reason="not_a_real_code",  # type: ignore[arg-type]
        )


def test_intent_is_routing_kind_only() -> None:
    decision = classify_turn("Hello there")
    assert decision.kind in RoutingKind
    assert decision.kind.value == "grounded_answer"
