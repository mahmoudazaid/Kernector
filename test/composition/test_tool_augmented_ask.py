"""Chat-time tool selection layered over the grounded ask path.

Doubles are duck-typed rather than imported from ``packs``: this module must not
load a pack at import time, so that ``import composition`` stays pack-free in a
fresh interpreter.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging

import pytest

from application import observability
from application.contracts import (
    AskRequest,
    AskResponse,
    Citation,
    InvokeToolResponse,
    RunMeta,
)
from application.errors import InsufficientEvidenceError
from application.grounded_rag_policy import INSUFFICIENT_KNOWLEDGE_ANSWER
from composition.tool_augmented_ask import ToolAugmentedAsk, ToolRunOutcome
from domain.knowledge import SourceReference
from domain.models import Message
from test.log_record import flatten_log_record, operation_payload, operation_records

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


def _outcome(
    tool_outputs: tuple[InvokeToolResponse, ...] = (),
) -> ToolRunOutcome:
    return ToolRunOutcome(answer="Scored risk.", tool_outputs=tool_outputs)


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

    assert response.answer == ask.response.answer
    assert response.run is not None
    assert response.run.path == "rag"
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

    assert response.answer == ask.response.answer
    assert response.run is not None
    assert response.run.path == "task_prompt"
    assert response.run.prompt_key == "story-review"
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
    assert response.run is not None
    assert response.run.path == "tools"
    assert response.run.tools == (
        "software_delivery.risk_score",
        "software_delivery.generate_test_cases",
    )
    assert '{"score": 62}' not in str(response.run)


def test_tool_turn_preserves_model_latency_and_tokens_on_run_meta() -> None:
    """Tools-path AskResult metadata must survive _merge_run into AskResponse.run."""
    from domain.models import Usage

    ask = _RecordingAsk()
    outcome = ToolRunOutcome(
        answer="Generated cases.",
        tool_outputs=(
            InvokeToolResponse("software_delivery.generate_test_cases", "{}"),
        ),
        run=RunMeta(
            model="test-model",
            latency_ms=42,
            usage=Usage(total_tokens=99),
        ),
    )
    wrapper = ToolAugmentedAsk(
        ask,
        runner=_RecordingRunner(outcome),
        select=lambda query: _Selection(generate_tests=True, output_style="steps"),
        pack_id="software-delivery",
    )

    response = wrapper.execute(
        AskRequest(query="Create test cases for AUTH-101", prompt_key=None)
    )

    assert response.run is not None
    assert response.run.path == "tools"
    assert response.run.latency_ms == 42
    assert response.run.model == "test-model"
    assert response.run.usage is not None
    assert response.run.usage.total_tokens == 99
    assert "Generated cases." not in str(response.run)


def test_a_tool_turn_exposes_run_view_via_consume_not_ask_response() -> None:
    """#178 carrier B: typed view stays off AskResponse; consume-once side path."""
    from composition.software_delivery_tools import SoftwareDeliveryRunView

    run_view = SoftwareDeliveryRunView(summary="Scored risk.", calls=())
    ask = _RecordingAsk()
    wrapper = ToolAugmentedAsk(
        ask,
        runner=_RecordingRunner(
            ToolRunOutcome(answer="Scored risk.", run_view=run_view)
        ),
        select=lambda query: _Selection(generate_tests=False, output_style="steps"),
    )

    response = wrapper.execute(
        AskRequest(query="Score the risk for AUTH-101", prompt_key=None)
    )

    assert "run_view" not in AskResponse.__dataclass_fields__
    assert response.answer == "Scored risk."
    assert wrapper.consume_tool_run_view() is run_view
    assert wrapper.consume_tool_run_view() is None


def test_a_rag_turn_leaves_consume_empty() -> None:
    wrapper = ToolAugmentedAsk(
        _RecordingAsk(),
        runner=_RecordingRunner(_outcome()),
        select=lambda query: None,
    )
    wrapper.execute(AskRequest(query="What is MFA?", prompt_key=None))
    assert wrapper.consume_tool_run_view() is None


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
    assert response.run is not None
    assert response.run.outcome == "insufficient"
    assert response.run.path == "tools"
    assert response.run.hit_count == 0
    assert response.run.citation_count == 0
    assert response.run.query_rewritten is None


def test_tool_turn_carries_retrieval_and_citation_counts_on_run_meta() -> None:
    ask = _RecordingAsk()
    outcome = ToolRunOutcome(
        answer="Scored risk.",
        citations=(
            Citation(
                reference=SourceReference("AUTH-101", "user_story"),
                quote="MFA is required.",
                chunk_index=0,
            ),
            Citation(
                reference=SourceReference("AUTH-101", "user_story"),
                quote="Lock after five attempts.",
                chunk_index=1,
            ),
        ),
        tool_outputs=(
            InvokeToolResponse("software_delivery.risk_score", '{"score": 62}'),
        ),
        run=RunMeta(hit_count=2, citation_count=2),
    )
    wrapper = ToolAugmentedAsk(
        ask,
        runner=_RecordingRunner(outcome),
        select=lambda query: _Selection(generate_tests=False, output_style="steps"),
        pack_id="software-delivery",
    )

    response = wrapper.execute(
        AskRequest(query="Score the risk for AUTH-101", prompt_key=None)
    )

    assert response.run is not None
    assert response.run.path == "tools"
    assert response.run.hit_count == 2
    assert response.run.citation_count == 2
    assert response.run.citation_count == len(response.citations)
    assert response.run.query_rewritten is None

    from presentation.streamlit.run_details import run_detail_lines

    joined = "\n".join(run_detail_lines(response.run))
    assert "Retrieval hits: 2" in joined
    assert "Citations: 2" in joined
    assert "Query rewritten:" not in joined


def test_rag_turn_still_preserves_ask_knowledge_rag_metadata() -> None:
    ask = _RecordingAsk()
    ask.response = AskResponse(
        answer="grounded answer",
        run=RunMeta(
            hit_count=1,
            citation_count=1,
            query_rewritten=True,
            outcome="success",
        ),
    )
    wrapper = ToolAugmentedAsk(
        ask,
        runner=_RecordingRunner(_outcome()),
        select=lambda query: None,
    )

    response = wrapper.execute(
        AskRequest(query="What is the session timeout?", prompt_key=None)
    )

    assert response.run is not None
    assert response.run.path == "rag"
    assert response.run.hit_count == 1
    assert response.run.citation_count == 1
    assert response.run.query_rewritten is True


def test_analysis_cues_fall_through_to_grounded_rag() -> None:
    """Former requirements-analysis phrasing stays on RAG; no dedicated runner."""
    from packs.software_delivery.chat_intent import select_chat_intent

    ask = _RecordingAsk()
    runner = _RecordingRunner(_outcome())
    wrapper = ToolAugmentedAsk(ask, runner=runner, select=select_chat_intent)
    query = "Analyze these requirements:\nAs a user I want MFA."
    request = AskRequest(query=query, prompt_key=None)

    response = wrapper.execute(request)

    assert select_chat_intent(query) is None
    assert response.answer == ask.response.answer
    assert response.run is not None
    assert response.run.path == "rag"
    assert ask.calls == [(request, None)]
    assert runner.runs == []


@pytest.mark.parametrize(
    "query",
    [
        "Create a summary, not test cases",
        "Create a summary of existing test cases",
        "Create a list of test cases",
        "How do I create test cases?",
        "Generate a report without creating tests",
        "How to write Gherkin scenarios",
        "Explain how to generate tests",
        "Do not create test cases for AUTH-101",
        "Never generate tests for AUTH-101",
        "Do not assess the risk for AUTH-101",
        "Do not analyze these requirements",
        "Analyze these requirements",
        "How do I analyze requirements?",
        "Analyze these requirements:\nNeed MFA enrollment.",
    ],
)
def test_rejected_intent_phrases_never_call_the_runner(query: str) -> None:
    """False positives must not reach retrieval or tools at the wrapper boundary."""
    from packs.software_delivery.chat_intent import select_chat_intent

    ask = _RecordingAsk()
    runner = _RecordingRunner(_outcome())
    wrapper = ToolAugmentedAsk(
        ask,
        runner=runner,
        select=select_chat_intent,
    )
    request = AskRequest(query=query, prompt_key=None)

    response = wrapper.execute(request)

    assert select_chat_intent(query) is None
    assert response.answer == ask.response.answer
    assert response.run is not None
    assert response.run.path == "rag"
    assert ask.calls == [(request, None)]
    assert runner.runs == []


@pytest.mark.parametrize(
    ("query", "generate_tests", "output_style"),
    [
        ("Create test cases that do not require admin access", True, "steps"),
        ("Create tests; never use production credentials", True, "steps"),
        (
            "Do not summarize the docs; create test cases for AUTH-101",
            True,
            "steps",
        ),
        ("Do not generate tests; assess the risk for AUTH-101", False, "steps"),
    ],
)
def test_accepted_intent_phrases_invoke_the_runner(
    query: str, generate_tests: bool, output_style: str
) -> None:
    """Constraint or other-clause negation must not cancel an active request."""
    from packs.software_delivery.chat_intent import select_chat_intent

    ask = _RecordingAsk()
    runner = _RecordingRunner(_outcome())
    wrapper = ToolAugmentedAsk(ask, runner=runner, select=select_chat_intent)

    response = wrapper.execute(AskRequest(query=query, prompt_key=None))

    assert runner.runs == [(query, generate_tests, output_style)]
    assert ask.calls == []
    assert response.answer == "Scored risk."
    assert response.tool_outputs == ()


def test_tools_path_run_meta_includes_tool_names_and_pack() -> None:
    ask = _RecordingAsk()
    outputs = (
        InvokeToolResponse(tool_name="score_risk", result="opaque-a"),
        InvokeToolResponse(tool_name="generate_tests", result="opaque-b"),
    )
    wrapper = ToolAugmentedAsk(
        ask,
        runner=_RecordingRunner(_outcome(tool_outputs=outputs)),
        select=lambda query: _Selection(generate_tests=True, output_style="steps"),
        pack_id="software-delivery",
    )

    response = wrapper.execute(AskRequest(query="Score risk for AUTH-101", prompt_key=None))

    assert response.run is not None
    assert response.run.outcome == "success"
    assert response.run.path == "tools"
    assert response.run.pack == "software-delivery"
    assert response.run.tools == ("score_risk", "generate_tests")
    assert "opaque-a" not in str(response.run)
    assert ask.calls == []


class _AskCapturingRequestId(_RecordingAsk):
    """Records the bound request_id while grounded ask runs."""

    def __init__(self) -> None:
        super().__init__()
        self.seen_request_id: str | None = None

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        self.seen_request_id = observability.current_request_id()
        return super().execute(request, settings)


def test_rag_turn_binds_request_id_and_logs_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ask = _AskCapturingRequestId()
    wrapper = ToolAugmentedAsk(
        ask, runner=_RecordingRunner(_outcome()), select=lambda query: None
    )
    # Correlation is owned by CorrelatedAsk; bind here to exercise nested logging.
    _bound, token = observability.bind_request_id()
    try:
        with caplog.at_level(logging.INFO, logger="composition.tool_augmented_ask"):
            wrapper.execute(
                AskRequest(query="What is the session timeout?", prompt_key=None)
            )
    finally:
        observability.reset_request_id(token)

    assert ask.seen_request_id is not None
    assert observability.current_request_id() is None
    records = operation_records(caplog.records, operation="ask_turn")
    assert len(records) == 1
    payload = operation_payload(records[0])
    assert payload["outcome"] == "delegated"
    assert payload["path"] == "rag"
    assert payload["request_id"] == ask.seen_request_id
    flat = flatten_log_record(records[0])
    assert "session timeout" not in flat


def test_tool_turn_logs_path_tools_with_shared_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ask = _RecordingAsk()
    seen: dict[str, str | None] = {}

    class _RunnerCapturingId(_RecordingRunner):
        def run(
            self,
            target: str,
            *,
            generate_tests: bool = True,
            output_style: str = "steps",
        ) -> ToolRunOutcome:
            seen["request_id"] = observability.current_request_id()
            return super().run(
                target, generate_tests=generate_tests, output_style=output_style
            )

    capturer = _RunnerCapturingId(
        ToolRunOutcome(
            answer="Scored risk.",
            tool_outputs=(InvokeToolResponse("software_delivery.risk_score", "{}"),),
        )
    )
    wrapper = ToolAugmentedAsk(
        ask,
        runner=capturer,
        select=lambda query: _Selection(generate_tests=False, output_style="steps"),
        pack_id="software-delivery",
    )
    _bound, token = observability.bind_request_id()
    try:
        with caplog.at_level(logging.INFO, logger="composition.tool_augmented_ask"):
            wrapper.execute(AskRequest(query="Score risk for AUTH-101", prompt_key=None))
    finally:
        observability.reset_request_id(token)

    assert seen["request_id"] is not None
    records = operation_records(caplog.records, operation="ask_turn")
    assert len(records) == 1
    payload = operation_payload(records[0])
    assert payload["path"] == "tools"
    assert payload["pack"] == "software-delivery"
    assert payload["request_id"] == seen["request_id"]
    flat = flatten_log_record(records[0])
    assert "AUTH-101" not in flat
    assert "Scored risk" not in flat
