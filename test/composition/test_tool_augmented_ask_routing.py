"""ToolAugmentedAsk dispatches after TurnRouter (#312)."""

from __future__ import annotations

from collections.abc import Mapping

from application.contracts import AskRequest, AskResponse
from application.turn_routing import WorkflowReadiness, WorkflowSignalResult
from composition.tool_augmented_ask import ToolAugmentedAsk, ToolRunOutcome
from composition.workflow_signals import TEST_DESIGN_CLARIFY_ANSWER
from domain.models import Message


class _RecordingAsk:
    def __init__(self, answer: str = "grounded") -> None:
        self.response = AskResponse(answer=answer)
        self.calls: list[AskRequest] = []

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        del settings
        self.calls.append(request)
        return self.response


class _ExplodingRunner:
    def run(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("runner must not be called")


def _incomplete_signal(hint: str = "test_design"):
    result = WorkflowSignalResult(
        workflow_hint=hint,
        readiness=WorkflowReadiness.INCOMPLETE,
        reason="missing_fields",
        missing_fields=("issue_locator",),
        clarification_context={
            "workflow_hint": hint,
            "missing_fields": ("issue_locator",),
        },
    )
    return lambda request: result


def test_task_prompt_skips_router_and_never_runs_tools() -> None:
    ask = _RecordingAsk()
    general = _RecordingAsk(answer="general")
    wrapper = ToolAugmentedAsk(
        ask,
        runner=_ExplodingRunner(),
        signals=(_incomplete_signal(),),
        ask_general=general,
    )
    request = AskRequest(query="design test", prompt_key="story-review")
    response = wrapper.execute(request)
    assert ask.calls == [request]
    assert general.calls == []
    assert response.run is not None
    assert response.run.path == "task_prompt"


def test_clarification_never_calls_grounded_or_general_ask() -> None:
    ask = _RecordingAsk()
    general = _RecordingAsk(answer="general")
    wrapper = ToolAugmentedAsk(
        ask,
        runner=_ExplodingRunner(),
        signals=(_incomplete_signal(),),
        ask_general=general,
    )
    response = wrapper.execute(AskRequest(query="design test"))
    assert ask.calls == []
    assert general.calls == []
    assert response.answer == TEST_DESIGN_CLARIFY_ANSWER
    assert response.run is not None
    assert response.run.path == "clarification"
    assert response.run.intent == "clarification"


def test_general_answer_never_calls_grounded_ask() -> None:
    ask = _RecordingAsk()
    general = _RecordingAsk(answer="brainstormed")
    wrapper = ToolAugmentedAsk(
        ask,
        runner=_ExplodingRunner(),
        signals=(),
        ask_general=general,
    )
    response = wrapper.execute(
        AskRequest(query="Brainstorm three creative taglines for a coffee brand")
    )
    assert ask.calls == []
    assert len(general.calls) == 1
    assert response.answer == "brainstormed"
    assert response.run is not None
    assert response.run.path == "general_answer"
    assert response.run.intent == "general_answer"


def test_bare_yes_history_does_not_run_tools() -> None:
    ask = _RecordingAsk()
    wrapper = ToolAugmentedAsk(
        ask,
        runner=_ExplodingRunner(),
        signals=(_incomplete_signal(),),
        ask_general=_RecordingAsk(answer="general"),
    )
    response = wrapper.execute(
        AskRequest(
            query="yes",
            history=(
                Message(role="user", content="design test"),
                Message(role="assistant", content=TEST_DESIGN_CLARIFY_ANSWER),
            ),
        )
    )
    # Incomplete signal still fires for "yes"? Our incomplete signal always
    # returns incomplete regardless of query — use empty signals for this case.
    del response
    wrapper = ToolAugmentedAsk(
        ask,
        runner=_ExplodingRunner(),
        signals=(),
        ask_general=_RecordingAsk(answer="general"),
    )
    response = wrapper.execute(
        AskRequest(
            query="yes",
            history=(
                Message(role="user", content="design test"),
                Message(role="assistant", content=TEST_DESIGN_CLARIFY_ANSWER),
            ),
        )
    )
    assert response.run is not None
    assert response.run.intent != "tool_workflow"
    assert response.run.path in {"rag", "clarification", "general_answer"}
