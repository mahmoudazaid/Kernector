"""Chat-time Software Delivery tool runs: recorder, retrieval guard, projection.

Doubles are duck-typed on the pack's outcome shapes rather than imported: this
module must not load ``packs`` at import time, and neither must its tests, so
that ``import composition`` stays pack-free in a fresh interpreter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pytest

from application.contracts import InvokeToolResponse
from application.errors import ApplicationValidationError, InsufficientEvidenceError
from composition.software_delivery_chat import (
    SOFTWARE_DELIVERY_TEST_STYLES,
    PackSoftwareDeliveryChat,
    ToolCallRecorder,
    ToolRunFailedError,
    project_software_delivery_run_view,
)
from composition.software_delivery_tools import (
    RiskFactorView,
    RiskScoreView,
    SoftwareDeliveryRunView,
    TestCaseView,
    TestCasesView,
)
from composition.tool_runs import ToolCallView
from domain.errors import ToolFailureError
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
)

_RISK_TOOL = "software_delivery.risk_score"
_GENERATE_TOOL = "software_delivery.generate_test_cases"
_EXPORT_TOOL = "software_delivery.export_test_cases_markdown"


@dataclass(frozen=True)
class _Factor:
    factor_id: str
    weight: int
    references: tuple[SourceReference, ...]


@dataclass(frozen=True)
class _Assessment:
    score: int
    level: str
    factors: tuple[_Factor, ...]
    rationale: str


@dataclass(frozen=True)
class _RiskOutcome:
    assessment: _Assessment


@dataclass(frozen=True)
class _Case:
    title: str
    steps: tuple[str, ...]
    expected: str
    references: tuple[SourceReference, ...]


@dataclass(frozen=True)
class _Generation:
    output_style: str
    test_cases: tuple[_Case, ...]


@dataclass(frozen=True)
class _TestsOutcome:
    result: _Generation


@dataclass(frozen=True)
class _ExportOutcome:
    markdown: str


@dataclass(frozen=True)
class _Response:
    summary: str
    outcomes: tuple[object, ...]


def _assessment() -> _Assessment:
    return _Assessment(
        score=62,
        level="high",
        factors=(
            _Factor(
                factor_id="missing_acceptance_criteria",
                weight=30,
                references=(SourceReference("SRS-2", "srs"),),
            ),
        ),
        rationale="Acceptance criteria are absent from a complete story.",
    )


def _hit(
    *,
    source_id: str = "AUTH-101",
    content: str = "MFA is required.",
    index: int = 0,
) -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(SourceReference(source_id, "user_story"), extra={}),
            index=index,
            content=content,
        ),
        score=0.9,
    )


class _RecordingRetrieve:
    def __init__(self, hits: tuple[ScoredChunk, ...]) -> None:
        self._hits = hits
        self.queries: list[str] = []

    def __call__(self, target: str) -> tuple[ScoredChunk, ...]:
        self.queries.append(target)
        return self._hits


class _RecordingOrchestrate:
    """Stands in for the lazily-imported pack call the container supplies."""

    def __init__(self, response: _Response, *, tools: Sequence[str] = (_RISK_TOOL,)) -> None:
        self._response = response
        self._tools = tuple(tools)
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> _Response:
        self.calls.append(dict(kwargs))
        for tool_name in self._tools:
            kwargs["invoke"](tool_name, {})  # type: ignore[operator]
        return self._response


def _ok(tool_name: str, arguments: Mapping[str, object]) -> str:
    return '{"score": 62}'


def test_each_successful_call_is_recorded_as_an_opaque_tool_output() -> None:
    """AC4: tool_outputs is the ledger of what actually ran, in call order."""
    recorder = ToolCallRecorder(_ok)

    recorder("software_delivery.risk_score", {})
    recorder("software_delivery.generate_test_cases", {})

    assert recorder.tool_outputs == (
        InvokeToolResponse("software_delivery.risk_score", '{"score": 62}'),
        InvokeToolResponse("software_delivery.generate_test_cases", '{"score": 62}'),
    )


def test_a_failed_call_is_not_recorded_as_an_output() -> None:
    """InvokeToolResponse rejects a blank result, so a failure has no entry."""

    def invoke(tool_name: str, arguments: Mapping[str, object]) -> str:
        if tool_name == "software_delivery.generate_test_cases":
            raise ToolFailureError("openrouter 502 for key sk-live-abc")
        return '{"score": 62}'

    recorder = ToolCallRecorder(invoke)
    recorder("software_delivery.risk_score", {})

    with pytest.raises(ToolFailureError):
        recorder("software_delivery.generate_test_cases", {})

    assert recorder.tool_outputs == (
        InvokeToolResponse("software_delivery.risk_score", '{"score": 62}'),
    )


def test_a_blank_result_cannot_become_a_tool_output() -> None:
    """An empty payload carries nothing and the contract will not hold it."""
    recorder = ToolCallRecorder(lambda tool_name, arguments: "")

    assert recorder("software_delivery.risk_score", {}) == ""
    assert recorder.tool_outputs == ()


def test_a_run_retrieves_orchestrates_and_reports_what_ran() -> None:
    """The whole seam, offline: nothing here touches a model or a vector store."""
    retrieve = _RecordingRetrieve((_hit(),))
    orchestrate = _RecordingOrchestrate(
        _Response("Scored risk.", (_RiskOutcome(_assessment()),))
    )
    runner = PackSoftwareDeliveryChat(
        retrieve=retrieve, invoke=_ok, orchestrate=orchestrate
    )

    outcome = runner.run(
        "Score the risk for AUTH-101", generate_tests=False, output_style="steps"
    )

    assert retrieve.queries == ["Score the risk for AUTH-101"]
    assert orchestrate.calls[0]["target"] == "Score the risk for AUTH-101"
    assert orchestrate.calls[0]["hits"] == (_hit(),)
    assert orchestrate.calls[0]["generate_tests"] is False
    assert orchestrate.calls[0]["output_style"] == "steps"
    assert outcome.tool_outputs == (
        InvokeToolResponse(_RISK_TOOL, '{"score": 62}'),
    )


def test_a_risk_only_run_answers_with_the_score_and_rationale() -> None:
    """AC1: the answer restates typed tool output, not improvised prose."""
    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=_RecordingOrchestrate(
            _Response("Scored risk.", (_RiskOutcome(_assessment()),))
        ),
    )

    outcome = runner.run("Score the risk for AUTH-101", generate_tests=False)

    assert outcome.answer == (
        "Scored risk.\n\n"
        "**Risk 62/100 (high)** — "
        "Acceptance criteria are absent from a complete story."
    )


def test_the_answer_carries_the_exported_cases_not_prose() -> None:
    """AC1: generated cases reach the reader as the export tool rendered them."""
    generation = _Generation(
        output_style="steps",
        test_cases=(
            _Case(
                title="Lock the account after five failed MFA attempts",
                steps=("Sign in with a valid password.", "Fail MFA five times."),
                expected="The account is locked.",
                references=(SourceReference("AUTH-101", "user_story"),),
            ),
        ),
    )
    markdown = "# Test Cases\n\n## 1. `Lock the account`\n"
    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=_RecordingOrchestrate(
            _Response(
                "Scored risk, generated test cases, and exported Markdown.",
                (
                    _RiskOutcome(_assessment()),
                    _TestsOutcome(generation),
                    _ExportOutcome(markdown),
                ),
            ),
            tools=(_RISK_TOOL, _GENERATE_TOOL, _EXPORT_TOOL),
        ),
    )

    outcome = runner.run("Create test cases for AUTH-101")

    assert outcome.answer.startswith(
        "Scored risk, generated test cases, and exported Markdown."
    )
    assert outcome.answer.endswith(markdown)
    assert outcome.tool_outputs == (
        InvokeToolResponse(_RISK_TOOL, '{"score": 62}'),
        InvokeToolResponse(_GENERATE_TOOL, '{"score": 62}'),
        InvokeToolResponse(_EXPORT_TOOL, '{"score": 62}'),
    )
    assert outcome.run_view is not None
    assert outcome.run_view.markdown == markdown
    assert outcome.run_view.risk is not None
    assert outcome.run_view.risk.score == 62


def test_a_risk_only_run_attaches_a_run_view_without_markdown() -> None:
    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=_RecordingOrchestrate(
            _Response("Scored risk.", (_RiskOutcome(_assessment()),))
        ),
    )

    outcome = runner.run("Score the risk for AUTH-101", generate_tests=False)

    assert outcome.run_view is not None
    assert outcome.run_view.markdown == ""
    assert outcome.run_view.test_cases is None
    assert outcome.run_view.risk is not None
    assert outcome.run_view.risk.score == 62
    assert outcome.run is not None
    assert outcome.run.hit_count == 1
    assert outcome.run.citation_count == 1
    assert outcome.run.model is None
    assert outcome.run.query_rewritten is None


def test_model_call_recorder_projects_latency_onto_tool_run_outcome() -> None:
    from composition.recording_chat import RecordingChatModel
    from domain.models import AskResult, Message, Usage

    class _Inner:
        def complete(
            self,
            system: str,
            messages: Sequence[Message],
            settings: Mapping[str, object],
        ) -> AskResult:
            return AskResult(
                content="{}",
                model="gen-model",
                latency_ms=55,
                usage=Usage(total_tokens=12),
            )

    recording = RecordingChatModel(_Inner())  # type: ignore[arg-type]

    def orchestrate(**kwargs: object) -> _Response:
        # Simulate the generate-test-cases tool calling the shared chat model.
        recording.complete("sys", (Message(role="user", content="q"),), {})
        kwargs["invoke"](_RISK_TOOL, {})  # type: ignore[operator]
        return _Response("Scored risk.", (_RiskOutcome(_assessment()),))

    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=orchestrate,
        model_calls=recording,
    )

    outcome = runner.run("Score the risk for AUTH-101", generate_tests=False)

    assert outcome.run is not None
    assert outcome.run.model == "gen-model"
    assert outcome.run.latency_ms == 55
    assert outcome.run.usage == Usage(total_tokens=12)
    assert outcome.run.settings == {}
    assert outcome.run.hit_count == 1
    assert outcome.run.citation_count == 1
    assert recording.consume() is None


def test_stale_recording_before_run_is_ignored_by_model_free_risk_run() -> None:
    from composition.recording_chat import RecordingChatModel
    from domain.models import AskResult, Message, Usage

    class _Inner:
        def complete(
            self,
            system: str,
            messages: Sequence[Message],
            settings: Mapping[str, object],
        ) -> AskResult:
            return AskResult(
                content="stale",
                model="stale-model",
                latency_ms=99,
                usage=Usage(total_tokens=1),
            )

    recording = RecordingChatModel(_Inner())  # type: ignore[arg-type]
    recording.complete("sys", (Message(role="user", content="prior"),), {})

    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=_RecordingOrchestrate(
            _Response("Scored risk.", (_RiskOutcome(_assessment()),))
        ),
        model_calls=recording,
    )

    outcome = runner.run("Score the risk for AUTH-101", generate_tests=False)

    assert outcome.run is not None
    assert outcome.run.model is None
    assert outcome.run.latency_ms is None
    assert outcome.run.hit_count == 1
    assert recording.consume() is None


def test_failed_run_clears_model_metadata_so_next_run_does_not_inherit_it() -> None:
    from composition.recording_chat import RecordingChatModel
    from domain.models import AskResult, Message, Usage

    class _Inner:
        def complete(
            self,
            system: str,
            messages: Sequence[Message],
            settings: Mapping[str, object],
        ) -> AskResult:
            return AskResult(
                content="{}",
                model="failed-run-model",
                latency_ms=44,
                usage=Usage(total_tokens=8),
            )

    recording = RecordingChatModel(_Inner())  # type: ignore[arg-type]

    def failing_orchestrate(**kwargs: object) -> _Response:
        recording.complete("sys", (Message(role="user", content="q"),), {})
        raise RuntimeError("orchestrate blew up")

    failing = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=failing_orchestrate,
        model_calls=recording,
    )
    with pytest.raises(ToolRunFailedError):
        failing.run("Create test cases for AUTH-101")

    assert recording.consume() is None

    following = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=_RecordingOrchestrate(
            _Response("Scored risk.", (_RiskOutcome(_assessment()),))
        ),
        model_calls=recording,
    )
    outcome = following.run("Score the risk for AUTH-101", generate_tests=False)

    assert outcome.run is not None
    assert outcome.run.model is None
    assert outcome.run.latency_ms is None
    assert outcome.run.hit_count == 1


def test_projection_failure_after_model_call_clears_recorder() -> None:
    """tool_run_answer / projection errors must not leak metadata to the next run."""
    from composition.recording_chat import RecordingChatModel
    from domain.models import AskResult, Message, Usage

    class _Inner:
        def complete(
            self,
            system: str,
            messages: Sequence[Message],
            settings: Mapping[str, object],
        ) -> AskResult:
            return AskResult(
                content="{}",
                model="proj-fail-model",
                latency_ms=33,
                usage=Usage(total_tokens=5),
            )

    recording = RecordingChatModel(_Inner())  # type: ignore[arg-type]

    def orchestrate(**kwargs: object) -> _Response:
        recording.complete("sys", (Message(role="user", content="q"),), {})
        kwargs["invoke"](_RISK_TOOL, {})  # type: ignore[operator]
        return _Response("Ran something new.", (object(),))

    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=orchestrate,
        model_calls=recording,
    )
    with pytest.raises(ToolRunFailedError):
        runner.run("Create test cases for AUTH-101")

    assert recording.consume() is None


def test_fake_recorder_protocol_works_without_inner_chat_model() -> None:
    """Orchestration depends on ModelCallRecorder, not RecordingChatModel."""
    from application.contracts import RunMeta
    from domain.models import Usage

    class _FakeRecorder:
        def __init__(self) -> None:
            self._meta: RunMeta | None = None
            self.cleared = 0

        def clear(self) -> None:
            self.cleared += 1
            self._meta = None

        def consume(self) -> RunMeta | None:
            last, self._meta = self._meta, None
            return last

        def seed(self, meta: RunMeta) -> None:
            self._meta = meta

    fake = _FakeRecorder()

    def orchestrate(**kwargs: object) -> _Response:
        fake.seed(
            RunMeta(
                model="fake-model",
                latency_ms=10,
                usage=Usage(total_tokens=2),
            )
        )
        kwargs["invoke"](_RISK_TOOL, {})  # type: ignore[operator]
        return _Response("Scored risk.", (_RiskOutcome(_assessment()),))

    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=orchestrate,
        model_calls=fake,
    )
    outcome = runner.run("Score the risk for AUTH-101", generate_tests=False)

    assert fake.cleared >= 2  # start + finally
    assert outcome.run is not None
    assert outcome.run.model == "fake-model"
    assert outcome.run.latency_ms == 10
    assert outcome.run.hit_count == 1


def test_every_citation_came_from_the_retrieved_evidence() -> None:
    """AC2: row-level provenance survives, because the bundle never touches it."""
    hits = (
        _hit(source_id="AUTH-101", content="MFA is required.", index=0),
        _hit(source_id="AUTH-101", content="Lock after five attempts.", index=1),
    )
    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve(hits),
        invoke=_ok,
        orchestrate=_RecordingOrchestrate(
            _Response("Scored risk.", (_RiskOutcome(_assessment()),))
        ),
    )

    outcome = runner.run("Score the risk for AUTH-101", generate_tests=False)

    assert {citation.quote for citation in outcome.citations} <= {
        hit.chunk.content for hit in hits
    }
    assert [citation.chunk_index for citation in outcome.citations] == [0, 1]
    assert all(
        citation.reference == SourceReference("AUTH-101", "user_story")
        for citation in outcome.citations
    )


def test_an_unrecognised_outcome_is_a_failure_not_a_silent_drop() -> None:
    """A new pack outcome must not vanish from the answer without anyone noticing."""
    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=_ok,
        orchestrate=_RecordingOrchestrate(_Response("Ran something new.", (object(),))),
    )

    with pytest.raises(ToolRunFailedError) as excinfo:
        runner.run("Score the risk for AUTH-101", generate_tests=False)

    assert str(excinfo.value) == "The tool run produced an unrecognised result."


def test_nothing_relevant_retrieved_is_an_outcome_not_a_crash() -> None:
    """An empty bundle would raise a pack validation error; say what happened."""
    orchestrate = _RecordingOrchestrate(_Response("unused", ()))
    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve(()), invoke=_ok, orchestrate=orchestrate
    )

    with pytest.raises(InsufficientEvidenceError):
        runner.run("Create test cases for AUTH-101")

    assert orchestrate.calls == []


def test_an_unknown_output_style_is_rejected_before_the_pack() -> None:
    retrieve = _RecordingRetrieve((_hit(),))
    orchestrate = _RecordingOrchestrate(_Response("unused", ()))
    runner = PackSoftwareDeliveryChat(
        retrieve=retrieve, invoke=_ok, orchestrate=orchestrate
    )

    with pytest.raises(ApplicationValidationError) as excinfo:
        runner.run("Create test cases for AUTH-101", output_style="prose")

    assert str(excinfo.value) == "output_style must be one of ['gherkin', 'steps']"
    assert retrieve.queries == []
    assert orchestrate.calls == []


def test_a_tool_failure_keeps_the_outputs_that_already_landed() -> None:
    """The reader learns which tools ran, never what the provider said."""

    def orchestrate(**kwargs: object) -> _Response:
        invoke = kwargs["invoke"]
        invoke(_RISK_TOOL, {})  # type: ignore[operator]
        invoke(_GENERATE_TOOL, {})  # type: ignore[operator]
        raise AssertionError("unreachable")

    def invoke(tool_name: str, arguments: Mapping[str, object]) -> str:
        if tool_name == _GENERATE_TOOL:
            raise ToolFailureError("openrouter 502 for key sk-live-abc")
        return '{"score": 62}'

    runner = PackSoftwareDeliveryChat(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=invoke,
        orchestrate=orchestrate,
    )

    with pytest.raises(ToolRunFailedError) as excinfo:
        runner.run("Create test cases for AUTH-101")

    assert str(excinfo.value) == "A tool failed during the run."
    assert "sk-live-abc" not in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, ToolFailureError)
    assert excinfo.value.tool_outputs == (
        InvokeToolResponse(_RISK_TOOL, '{"score": 62}'),
    )


def test_exported_styles_match_the_pack() -> None:
    """A composition constant that drifts from the pack would 400 at the tool."""
    from packs.software_delivery.contracts import TEST_CASE_STYLES

    assert set(SOFTWARE_DELIVERY_TEST_STYLES) == set(TEST_CASE_STYLES)


def _generation() -> _Generation:
    return _Generation(
        output_style="steps",
        test_cases=(
            _Case(
                title="Lock the account after five failed MFA attempts",
                steps=("Sign in with a valid password.", "Fail MFA five times."),
                expected="The account is locked.",
                references=(SourceReference("AUTH-101", "user_story"),),
            ),
        ),
    )


def test_project_run_view_maps_full_chain_to_typed_views() -> None:
    """#178: typed outcomes become SoftwareDeliveryRunView without opaque payloads."""
    markdown = "# Test Cases\n\n## 1. `Lock the account`\n"
    response = _Response(
        "Scored risk, generated test cases, and exported Markdown.",
        (
            _RiskOutcome(_assessment()),
            _TestsOutcome(_generation()),
            _ExportOutcome(markdown),
        ),
    )

    view = project_software_delivery_run_view(response)

    assert view == SoftwareDeliveryRunView(
        summary="Scored risk, generated test cases, and exported Markdown.",
        calls=(
            ToolCallView(
                _RISK_TOOL, ok=True, summary="Scored risk at 62/100"
            ),
            ToolCallView(
                _GENERATE_TOOL, ok=True, summary="Generated 1 test case"
            ),
            ToolCallView(
                _EXPORT_TOOL, ok=True, summary="Exported test cases as Markdown"
            ),
        ),
        risk=RiskScoreView(
            score=62,
            level="high",
            rationale="Acceptance criteria are absent from a complete story.",
            factors=(
                RiskFactorView(
                    factor_id="missing_acceptance_criteria",
                    weight=30,
                    references=(SourceReference("SRS-2", "srs"),),
                ),
            ),
        ),
        test_cases=TestCasesView(
            output_style="steps",
            cases=(
                TestCaseView(
                    title="Lock the account after five failed MFA attempts",
                    steps=(
                        "Sign in with a valid password.",
                        "Fail MFA five times.",
                    ),
                    expected="The account is locked.",
                    references=(SourceReference("AUTH-101", "user_story"),),
                ),
            ),
        ),
        markdown=markdown,
    )
    rendered = " ".join(call.summary for call in view.calls)
    assert '{"score"' not in rendered
    assert "sk-live" not in rendered


def test_project_run_view_maps_risk_only_without_export() -> None:
    view = project_software_delivery_run_view(
        _Response("Scored risk.", (_RiskOutcome(_assessment()),))
    )

    assert view.risk is not None
    assert view.risk.score == 62
    assert view.test_cases is None
    assert view.markdown == ""
    assert view.calls == (
        ToolCallView(_RISK_TOOL, ok=True, summary="Scored risk at 62/100"),
    )


def test_project_run_view_rejects_unrecognised_outcome() -> None:
    with pytest.raises(ToolRunFailedError) as excinfo:
        project_software_delivery_run_view(
            _Response("Ran something new.", (object(),))
        )

    assert str(excinfo.value) == "The tool run produced an unrecognised result."
