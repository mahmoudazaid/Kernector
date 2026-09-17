"""WorkflowSignals for Test Design and Drive export (#312 / #304 / #310)."""

from __future__ import annotations

from application.turn_routing import (
    RoutingKind,
    TurnRoutingRequest,
    WorkflowReadiness,
    classify_turn,
)
from composition.workflow_signals import (
    DRIVE_MISSING_PAYLOAD_CLARIFY_ANSWER,
    DRIVE_PARTIAL_CLARIFY_ANSWER,
    DRIVE_UNAVAILABLE_CLARIFY_ANSWER,
    TEST_DESIGN_CLARIFY_ANSWER,
    build_drive_export_workflow_signal,
    build_test_design_workflow_signal,
    clarification_answer_for,
)


def test_test_design_command_without_issue_is_incomplete() -> None:
    signal = build_test_design_workflow_signal(enabled=True)
    result = signal(TurnRoutingRequest(query="design test"))
    assert result is not None
    assert result.readiness is WorkflowReadiness.INCOMPLETE
    assert result.reason == "missing_fields"
    assert "issue_locator" in result.missing_fields


def test_test_design_command_with_issue_is_ready() -> None:
    signal = build_test_design_workflow_signal(enabled=True)
    result = signal(
        TurnRoutingRequest(query="Design tests for acme/api#42")
    )
    assert result is not None
    assert result.readiness is WorkflowReadiness.READY


def test_test_design_topical_question_is_not_a_workflow_signal() -> None:
    signal = build_test_design_workflow_signal(enabled=True)
    assert signal(
        TurnRoutingRequest(query="How does test design work in this repo?")
    ) is None


def test_test_design_project_question_without_leading_qword_is_not_a_signal() -> None:
    signal = build_test_design_workflow_signal(enabled=True)
    assert signal(
        TurnRoutingRequest(
            query="Summarize our test design guidelines from the docs"
        )
    ) is None


def test_test_design_command_with_issue_noun_still_clarifies() -> None:
    """#304: natural commands that name 'issue'/'docs' still clarify."""
    signal = build_test_design_workflow_signal(enabled=True)
    for query in (
        "Start test design for this issue",
        "design tests for the login issue",
        "start test design for our repo",
        "Design tests for the GitHub issue we discussed",
        "plan coverage for the docs",
    ):
        result = signal(TurnRoutingRequest(query=query))
        assert result is not None, query
        assert result.readiness is WorkflowReadiness.INCOMPLETE, query
        assert result.reason == "missing_fields", query


def test_partial_drive_export_is_incomplete() -> None:
    signal = build_drive_export_workflow_signal(
        export_enabled=True, draft_ready=lambda _cid: True
    )
    for query in ("export", "export the selected tests", "send this to Drive"):
        result = signal(TurnRoutingRequest(query=query))
        assert result is not None, query
        assert result.readiness is WorkflowReadiness.INCOMPLETE
        assert result.reason == "incomplete_workflow"


def test_prose_mention_of_export_is_not_a_drive_signal() -> None:
    signal = build_drive_export_workflow_signal(
        export_enabled=True, draft_ready=lambda _cid: False
    )
    for query in (
        "What do our docs say about the export pipeline?",
        "According to the README, how is data export configured?",
        "According to our docs, how does the export to Google Drive connector work?",
        "What do the docs say about Google Drive export permissions?",
        "Explain the Drive export flow in this repo",
    ):
        assert signal(TurnRoutingRequest(query=query)) is None, query
    decision = classify_turn(
        "According to our docs, how does the export to Google Drive connector work?",
        signals=(signal,),
        conversation_id="c1",
    )
    assert decision.kind == RoutingKind.GROUNDED_ANSWER


def test_drive_docs_prose_stays_on_rag_when_export_disabled() -> None:
    signal = build_drive_export_workflow_signal(
        export_enabled=False, draft_ready=lambda _cid: False
    )
    query = (
        "According to our docs, how does the export to Google Drive connector work?"
    )
    assert signal(TurnRoutingRequest(query=query)) is None
    decision = classify_turn(query, signals=(signal,), conversation_id="c1")
    assert decision.kind == RoutingKind.GROUNDED_ANSWER
    assert decision.reason != "tool_unavailable"


def test_clear_drive_export_without_payload_is_incomplete() -> None:
    signal = build_drive_export_workflow_signal(
        export_enabled=True, draft_ready=lambda _cid: False
    )
    result = signal(
        TurnRoutingRequest(
            query="export to google drive",
            conversation_id="conv-1",
        )
    )
    assert result is not None
    assert result.readiness is WorkflowReadiness.INCOMPLETE
    assert result.reason == "missing_fields"
    assert clarification_answer_for(result.reason, result.workflow_hint) == (
        DRIVE_MISSING_PAYLOAD_CLARIFY_ANSWER
    )


def test_clear_drive_export_with_payload_is_ready() -> None:
    signal = build_drive_export_workflow_signal(
        export_enabled=True, draft_ready=lambda _cid: True
    )
    result = signal(
        TurnRoutingRequest(
            query="export to google drive",
            conversation_id="conv-1",
        )
    )
    assert result is not None
    assert result.readiness is WorkflowReadiness.READY


def test_drive_export_when_disabled_is_tool_unavailable_not_rag() -> None:
    signal = build_drive_export_workflow_signal(
        export_enabled=False, draft_ready=lambda _cid: True
    )
    result = signal(TurnRoutingRequest(query="export to google drive"))
    assert result is not None
    assert result.reason == "tool_unavailable"
    decision = classify_turn(
        "export to google drive",
        signals=(signal,),
    )
    assert decision.kind == RoutingKind.CLARIFICATION
    assert decision.reason == "tool_unavailable"
    assert clarification_answer_for(decision.reason, decision.workflow_hint) == (
        DRIVE_UNAVAILABLE_CLARIFY_ANSWER
    )


def test_conflicting_test_design_and_drive_signals_clarify() -> None:
    decision = classify_turn(
        "design tests for acme/api#1 and export to google drive",
        signals=(
            build_test_design_workflow_signal(enabled=True),
            build_drive_export_workflow_signal(
                export_enabled=True, draft_ready=lambda _cid: True
            ),
        ),
        conversation_id="conv-1",
    )
    assert decision.kind == RoutingKind.CLARIFICATION
    assert decision.reason == "conflicting_workflows"


def test_clarification_copy_for_test_design() -> None:
    assert (
        clarification_answer_for("missing_fields", "test_design")
        == TEST_DESIGN_CLARIFY_ANSWER
    )
    assert (
        clarification_answer_for("incomplete_workflow", "drive_export")
        == DRIVE_PARTIAL_CLARIFY_ANSWER
    )
