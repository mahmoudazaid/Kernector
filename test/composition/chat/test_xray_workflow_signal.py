"""Xray export WorkflowSignal and its ToolAugmentedAsk branch (#199)."""

from __future__ import annotations

import pytest

from application.contracts import AskRequest, AskResponse
from application.turn_routing import (
    RoutingKind,
    TurnRoutingRequest,
    WorkflowReadiness,
    classify_turn,
)
from composition.chat.tool_augmented_ask import ToolAugmentedAsk, ToolRunOutcome
from composition.chat.workflow_signals import (
    XRAY_MISSING_CASES_CLARIFY_ANSWER,
    XRAY_UNAVAILABLE_CLARIFY_ANSWER,
    build_drive_export_workflow_signal,
    build_test_design_workflow_signal,
    build_xray_export_workflow_signal,
    clarification_answer_for,
)
from composition.xray_export.prepare import XRAY_EXPORT_TARGET


def _signal(*, enabled: bool = True, ready: bool = True):
    return build_xray_export_workflow_signal(
        export_enabled=enabled, draft_ready=lambda _cid: ready
    )


@pytest.mark.parametrize(
    "query",
    ["create xray tests", "Export the test cases to Xray", "push these tests to xray"],
)
def test_clear_xray_request_with_generated_cases_is_ready(query: str) -> None:
    result = _signal()(TurnRoutingRequest(query=query, conversation_id="conv-1"))

    assert result is not None
    assert result.workflow_hint == "xray_export"
    assert result.readiness is WorkflowReadiness.READY


def test_xray_request_without_generated_cases_is_missing_fields() -> None:
    result = _signal(ready=False)(
        TurnRoutingRequest(query="create xray tests", conversation_id="conv-1")
    )

    assert result is not None
    assert result.reason == "missing_fields"
    assert clarification_answer_for(result.reason, result.workflow_hint) == (
        XRAY_MISSING_CASES_CLARIFY_ANSWER
    )


def test_xray_request_when_disabled_is_tool_unavailable_not_rag() -> None:
    decision = classify_turn("create xray tests", signals=(_signal(enabled=False),))

    assert decision.kind == RoutingKind.CLARIFICATION
    assert decision.reason == "tool_unavailable"
    assert clarification_answer_for(decision.reason, decision.workflow_hint) == (
        XRAY_UNAVAILABLE_CLARIFY_ANSWER
    )


@pytest.mark.parametrize(
    "query",
    [
        "how does the xray export work in this project?",
        "what is xray",
        "export to google drive",
        "design tests for acme/api#1",
    ],
)
def test_non_requests_are_not_xray_signals(query: str) -> None:
    assert _signal()(TurnRoutingRequest(query=query, conversation_id="conv-1")) is None


def test_drive_and_test_design_signals_ignore_xray_requests() -> None:
    request = TurnRoutingRequest(query="create xray tests", conversation_id="conv-1")

    assert build_test_design_workflow_signal(enabled=True)(request) is None
    assert (
        build_drive_export_workflow_signal(export_enabled=True, draft_ready=lambda _c: True)(
            request
        )
        is None
    )


def test_xray_readiness_reads_the_conversation_draft() -> None:
    from test.packs.software_delivery.tools.test_create_xray_tests import (
        _candidate,
        _draft,
        _manual_case,
    )

    class _Drafts:
        def find_by_conversation_id(self, conversation_id: str):
            assert conversation_id == "conv-1"
            return _draft(candidates=(_candidate("cand-1"),), cases=(_manual_case("cand-1"),))

    signal = build_xray_export_workflow_signal(export_enabled=True, drafts=_Drafts())

    result = signal(TurnRoutingRequest(query="create xray tests", conversation_id="conv-1"))

    assert result is not None
    assert result.readiness is WorkflowReadiness.READY


class _Ask:
    def execute(self, request, settings=None):  # noqa: ANN001
        raise AssertionError("grounded ask must not run")


class _Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def run(self, target: str, **kwargs: object) -> ToolRunOutcome:
        self.calls.append((target, kwargs))
        return ToolRunOutcome(answer="created")


def test_ready_xray_turn_runs_tools_with_the_fixed_target_and_no_evidence() -> None:
    runner = _Runner()
    ask = ToolAugmentedAsk(
        _Ask(),  # type: ignore[arg-type]
        runner=runner,  # type: ignore[arg-type]
        signals=(_signal(),),
        ask_general=_Ask(),  # type: ignore[arg-type]
        pack_id="software-delivery",
    )

    response = ask.execute(
        AskRequest(query="please create xray tests", conversation_id="conv-1")
    )

    assert isinstance(response, AskResponse)
    assert response.answer == "created"
    [(target, kwargs)] = runner.calls
    assert target == XRAY_EXPORT_TARGET
    assert kwargs["need_evidence"] is False
    assert kwargs["conversation_id"] == "conv-1"
