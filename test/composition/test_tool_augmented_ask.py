"""Chat-time tool selection layered over the grounded ask path.

Doubles are duck-typed rather than imported from ``packs``: this module must not
load a pack at import time, so that ``import composition`` stays pack-free in a
fresh interpreter.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from application.contracts import (
    AskRequest,
    AskResponse,
    Citation,
    InvokeToolResponse,
)
from application.errors import InsufficientEvidenceError
from application.grounded_rag_policy import INSUFFICIENT_KNOWLEDGE_ANSWER
from composition.tool_augmented_ask import ToolAugmentedAsk, ToolRunOutcome
from domain.knowledge import SourceReference
from domain.models import Message


@dataclass(frozen=True)
class _Selection:
    """Stands in for the pack's ChatToolSelection."""

    generate_tests: bool
    output_style: str


class _RecordingAsk:
    """A grounded ask that records what it was handed."""

    def __init__(self) -> None:
        self.response = AskResponse(answer="grounded answer")
        self.calls: list[tuple[AskRequest, Mapping[str, object] | None]] = []

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        self.calls.append((request, settings))
        return self.response


class _RecordingRunner:
    """Stands in for the tool-run adapter the container wires lazily."""

    def __init__(self, outcome: ToolRunOutcome) -> None:
        self._outcome = outcome
        self.runs: list[tuple[str, bool, str]] = []

    def run(
        self,
        target: str,
        *,
        generate_tests: bool = True,
        output_style: str = "steps",
    ) -> ToolRunOutcome:
        self.runs.append((target, generate_tests, output_style))
        return self._outcome


def _outcome() -> ToolRunOutcome:
    return ToolRunOutcome(answer="Scored risk.")


def test_an_unmatched_query_is_answered_by_grounded_rag() -> None:
    """AC3: an ordinary question keeps the existing path and calls no tool."""
    ask = _RecordingAsk()
    runner = _RecordingRunner(_outcome())
    wrapper = ToolAugmentedAsk(ask, runner=runner, select=lambda query: None)
    request = AskRequest(
        query="What is the session timeout?",
        prompt_key=None,
        history=(Message(role="user", content="Hello"),),
    )

    response = wrapper.execute(request, settings={"temperature": 0})

    assert response is ask.response
    assert ask.calls == [(request, {"temperature": 0})]
    assert runner.runs == []


def test_a_selected_mode_delegates_verbatim_without_calling_the_runner() -> None:
    """Tool selection is General-mode only; task prompts stay on grounded RAG."""
    ask = _RecordingAsk()
    runner = _RecordingRunner(_outcome())
    wrapper = ToolAugmentedAsk(
        ask,
        runner=runner,
        select=lambda query: _Selection(generate_tests=True, output_style="steps"),
    )
    request = AskRequest(
        query="Create test cases for AUTH-101",
        prompt_key="story-review",
        history=(Message(role="user", content="Hello"),),
    )
    settings = {"temperature": 0.2}

    response = wrapper.execute(request, settings=settings)

    assert response is ask.response
    assert ask.calls == [(request, settings)]
    assert runner.runs == []


def test_a_matched_intent_runs_the_tools_and_reports_their_outputs() -> None:
    """AC1 + AC4: the chain runs and its opaque results reach the response."""
    ask = _RecordingAsk()
    outcome = ToolRunOutcome(
        answer="Scored risk, generated test cases, and exported Markdown.",
        citations=(
            Citation(
                reference=SourceReference("AUTH-101", "user_story"),
                quote="MFA is required.",
                chunk_index=0,
            ),
        ),
        tool_outputs=(
            InvokeToolResponse("software_delivery.risk_score", '{"score": 62}'),
            InvokeToolResponse("software_delivery.generate_test_cases", '{"a": 1}'),
        ),
    )
    runner = _RecordingRunner(outcome)
    wrapper = ToolAugmentedAsk(
        ask,
        runner=runner,
        select=lambda query: _Selection(generate_tests=True, output_style="steps"),
    )

    response = wrapper.execute(
        AskRequest(
            query="Create test cases for AUTH-101",
            prompt_key=None,
            history=(Message(role="user", content="Hello"),),
        )
    )

    assert runner.runs == [("Create test cases for AUTH-101", True, "steps")]
    assert ask.calls == []
    assert response.answer == outcome.answer
    assert response.citations == outcome.citations
    assert response.tool_outputs == outcome.tool_outputs
    assert response.run is None


def test_the_selected_style_reaches_the_chain() -> None:
    runner = _RecordingRunner(_outcome())
    wrapper = ToolAugmentedAsk(
        _RecordingAsk(),
        runner=runner,
        select=lambda query: _Selection(generate_tests=True, output_style="gherkin"),
    )

    wrapper.execute(
        AskRequest(
            query="Write gherkin test cases for AUTH-101",
            prompt_key=None,
        )
    )

    assert runner.runs == [("Write gherkin test cases for AUTH-101", True, "gherkin")]


def test_no_relevant_evidence_falls_back_to_the_grounded_insufficient_answer() -> None:
    """Chat must not invent a second vocabulary for "I don't know"."""

    class _EmptyRunner:
        def run(
            self,
            target: str,
            *,
            generate_tests: bool = True,
            output_style: str = "steps",
        ) -> ToolRunOutcome:
            raise InsufficientEvidenceError("nothing cleared the threshold")

    wrapper = ToolAugmentedAsk(
        _RecordingAsk(),
        runner=_EmptyRunner(),
        select=lambda query: _Selection(generate_tests=True, output_style="steps"),
    )

    response = wrapper.execute(
        AskRequest(query="Create test cases for AUTH-101", prompt_key=None)
    )

    assert response.answer == INSUFFICIENT_KNOWLEDGE_ANSWER
    assert response.tool_outputs == ()
    assert response.citations == ()
