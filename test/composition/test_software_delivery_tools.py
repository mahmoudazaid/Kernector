"""Behavior tests for the Software Delivery composition views and runner.

Doubles are duck-typed on the pack's outcome shapes rather than imported: this
module must not load ``packs`` at import time, and neither must its tests, so
that ``import composition`` stays pack-free in a fresh interpreter.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from application.errors import ApplicationValidationError, InsufficientEvidenceError
from composition.software_delivery_tools import (
    SOFTWARE_DELIVERY_TEST_STYLES,
    PackSoftwareDeliveryTools,
    RiskFactorView,
    TestCaseView,
    TestCasesView,
    run_view,
    software_delivery_tools_enabled,
)
from composition.tool_runs import ToolCallView, ToolRunFailedError
from domain.errors import ToolFailureError
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
)


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


def _hit(*, source_id: str = "US-1", content: str = "MFA is required.") -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(SourceReference(source_id, "user_story"), extra={}),
            index=0,
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

    def __init__(self, response: _Response) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> _Response:
        self.calls.append(dict(kwargs))
        kwargs["invoke"]("software_delivery.risk_score", {})  # type: ignore[operator]
        return self._response


class _Settings:
    """Duck-typed stand-in: reads ``domain_tools.enabled_packs`` only."""

    def __init__(self, *packs: str) -> None:
        self.domain_tools = SimpleNamespace(enabled_packs=packs)


def test_risk_outcome_projects_score_rationale_and_factor_references() -> None:
    """AC2: score, rationale and provenance are all on the view."""
    response = _Response("Scored risk.", (_RiskOutcome(_assessment()),))
    calls = (ToolCallView("software_delivery.risk_score", ok=True, result="{}"),)

    view = run_view(response, calls)

    assert view.summary == "Scored risk."
    assert view.calls == calls
    assert view.risk is not None
    assert view.risk.score == 62
    assert view.risk.level == "high"
    assert view.risk.rationale == (
        "Acceptance criteria are absent from a complete story."
    )
    assert view.risk.factors == (
        RiskFactorView(
            factor_id="missing_acceptance_criteria",
            weight=30,
            references=(SourceReference("SRS-2", "srs"),),
        ),
    )
    assert view.test_cases is None
    assert view.markdown == ""


def test_generated_cases_and_markdown_reach_the_view() -> None:
    """AC3 + AC4: the structured cases and the exportable file both survive."""
    generation = _Generation(
        output_style="steps",
        test_cases=(
            _Case(
                title="Lock the account after five failed MFA attempts",
                steps=("Sign in with a valid password.", "Fail MFA five times."),
                expected="The account is locked and an alert is raised.",
                references=(SourceReference("US-1", "user_story"),),
            ),
        ),
    )
    response = _Response(
        "Scored risk, generated test cases, and exported Markdown.",
        (
            _RiskOutcome(_assessment()),
            _TestsOutcome(generation),
            _ExportOutcome("# Test Cases\n"),
        ),
    )

    view = run_view(response, ())

    assert view.test_cases is not None
    assert view.test_cases.output_style == "steps"
    assert view.test_cases.cases == (
        TestCaseView(
            title="Lock the account after five failed MFA attempts",
            steps=("Sign in with a valid password.", "Fail MFA five times."),
            expected="The account is locked and an alert is raised.",
            references=(SourceReference("US-1", "user_story"),),
        ),
    )
    assert view.markdown == "# Test Cases\n"
    assert view.risk is not None


def test_an_unrecognised_outcome_is_a_failure_not_a_silent_drop() -> None:
    """A new pack outcome must not vanish from the UI without anyone noticing."""
    response = _Response("Ran something new.", (object(),))

    with pytest.raises(ToolRunFailedError) as excinfo:
        run_view(response, ())

    assert str(excinfo.value) == "The tool run produced an unrecognised result."


def test_tool_run_surface_is_absent_when_the_pack_is_disabled() -> None:
    assert software_delivery_tools_enabled(_Settings()) is False
    assert software_delivery_tools_enabled(_Settings("other-pack")) is False


def test_tool_run_surface_appears_when_the_pack_is_enabled() -> None:
    assert software_delivery_tools_enabled(_Settings("software-delivery")) is True


def test_exported_styles_match_the_pack() -> None:
    """A composition constant that drifts from the pack would 400 at the tool."""
    from packs.software_delivery.contracts import TEST_CASE_STYLES

    assert set(SOFTWARE_DELIVERY_TEST_STYLES) == set(TEST_CASE_STYLES)


def test_a_run_retrieves_orchestrates_and_returns_the_ledger_with_the_view() -> None:
    """The whole seam, offline: nothing here touches a model or a vector store."""
    retrieve = _RecordingRetrieve((_hit(),))
    orchestrate = _RecordingOrchestrate(
        _Response("Scored risk.", (_RiskOutcome(_assessment()),))
    )
    runner = PackSoftwareDeliveryTools(
        retrieve=retrieve,
        invoke=lambda name, arguments: "{}",
        orchestrate=orchestrate,
    )

    view = runner.run("Assess MFA rollout", generate_tests=False, output_style="steps")

    assert retrieve.queries == ["Assess MFA rollout"]
    assert orchestrate.calls[0]["target"] == "Assess MFA rollout"
    assert orchestrate.calls[0]["generate_tests"] is False
    assert orchestrate.calls[0]["output_style"] == "steps"
    assert orchestrate.calls[0]["hits"] == (_hit(),)
    assert view.risk is not None
    assert view.calls == (
        ToolCallView("software_delivery.risk_score", ok=True, result="{}"),
    )


def test_nothing_relevant_retrieved_is_an_outcome_not_a_crash() -> None:
    """An empty bundle would raise a pack validation error; say what happened instead."""
    orchestrate = _RecordingOrchestrate(_Response("unused", ()))
    runner = PackSoftwareDeliveryTools(
        retrieve=_RecordingRetrieve(()),
        invoke=lambda name, arguments: "{}",
        orchestrate=orchestrate,
    )

    with pytest.raises(InsufficientEvidenceError):
        runner.run("Assess MFA rollout")

    assert orchestrate.calls == []


def test_an_unknown_output_style_is_rejected_before_the_pack() -> None:
    orchestrate = _RecordingOrchestrate(_Response("unused", ()))
    runner = PackSoftwareDeliveryTools(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=lambda name, arguments: "{}",
        orchestrate=orchestrate,
    )

    with pytest.raises(ApplicationValidationError) as excinfo:
        runner.run("Assess MFA rollout", output_style="prose")

    assert str(excinfo.value) == "output_style must be one of ['gherkin', 'steps']"
    assert orchestrate.calls == []


def test_a_tool_failure_keeps_the_calls_that_already_ran() -> None:
    """AC5: the reader learns which tool failed, not what it said."""

    def orchestrate(**kwargs: object) -> _Response:
        invoke = kwargs["invoke"]
        invoke("software_delivery.risk_score", {})  # type: ignore[operator]
        invoke("software_delivery.generate_test_cases", {})  # type: ignore[operator]
        raise AssertionError("unreachable")

    def invoke(tool_name: str, arguments: object) -> str:
        if tool_name == "software_delivery.generate_test_cases":
            raise ToolFailureError("openrouter 502 for key sk-live-abc")
        return "{}"

    runner = PackSoftwareDeliveryTools(
        retrieve=_RecordingRetrieve((_hit(),)),
        invoke=invoke,
        orchestrate=orchestrate,
    )

    with pytest.raises(ToolRunFailedError) as excinfo:
        runner.run("Assess MFA rollout")

    assert str(excinfo.value) == "A tool failed during the run."
    assert "sk-live-abc" not in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, ToolFailureError)
    assert excinfo.value.calls == (
        ToolCallView("software_delivery.risk_score", ok=True, result="{}"),
        ToolCallView("software_delivery.generate_test_cases", ok=False, result=""),
    )
