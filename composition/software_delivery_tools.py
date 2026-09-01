"""Composition-facing views and runner for Software Delivery tool runs.

Projects the pack's typed orchestration outcomes onto composition dataclasses
so presentation can render risk, test cases and Markdown without importing
``packs``. Pack types are matched structurally, never imported: this module is
reachable from ``import composition``, which must not load a pack.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from application.errors import ApplicationValidationError, InsufficientEvidenceError
from composition.tool_runs import (
    OpaqueInvoke,
    ToolCallRecorder,
    ToolCallView,
    ToolRunFailedError,
)
from domain.errors import DomainValidationError
from domain.knowledge import ScoredChunk, SourceReference
from infrastructure.config import Settings

_PACK_ID = "software-delivery"

# Duplicated from the pack's TEST_CASE_STYLES on purpose: presentation needs the
# option list, and importing the pack here would load it at ``import composition``
# time. The drift is pinned by test_exported_styles_match_the_pack.
SOFTWARE_DELIVERY_TEST_STYLES: tuple[str, ...] = ("steps", "gherkin")

_TOOL_RUN_FAILED_MESSAGE = "A tool failed during the run."
_NO_EVIDENCE_MESSAGE = (
    "No ingested document was relevant enough to ground this tool run."
)
_UNKNOWN_OUTCOME_MESSAGE = "The tool run produced an unrecognised result."


@dataclass(frozen=True, slots=True)
class RiskFactorView:
    """One contributing risk factor with its supporting provenance.

    Attributes:
        factor_id (str): Pack-authored factor identifier.
        weight (int): Positive contribution to the score.
        references (tuple[SourceReference, ...]): Sources supporting the factor.
    """

    factor_id: str
    weight: int
    references: tuple[SourceReference, ...]


@dataclass(frozen=True, slots=True)
class RiskScoreView:
    """Structured risk assessment exposed at the composition boundary.

    Attributes:
        score (int): Risk score in 0..100.
        level (str): Pack-authored band, one of low/medium/high/critical.
        rationale (str): Why the score came out where it did.
        factors (tuple[RiskFactorView, ...]): Contributing factors, cited.
    """

    score: int
    level: str
    rationale: str
    factors: tuple[RiskFactorView, ...]


@dataclass(frozen=True, slots=True)
class TestCaseView:
    """One generated test case with its provenance.

    Attributes:
        title (str): Case title as generated.
        steps (tuple[str, ...]): Ordered steps.
        expected (str): Expected result.
        references (tuple[SourceReference, ...]): Sources the case rests on.
    """

    __test__ = False

    title: str
    steps: tuple[str, ...]
    expected: str
    references: tuple[SourceReference, ...]


@dataclass(frozen=True, slots=True)
class TestCasesView:
    """Generated test cases exposed at the composition boundary.

    Attributes:
        output_style (str): ``steps`` or ``gherkin``.
        cases (tuple[TestCaseView, ...]): Cases in generated order.
    """

    __test__ = False

    output_style: str
    cases: tuple[TestCaseView, ...]


@dataclass(frozen=True, slots=True)
class SoftwareDeliveryRunView:
    """One tool run: the generic ledger plus whatever structured output it produced.

    Attributes:
        summary (str): Deterministic pack summary of what ran.
        calls (tuple[ToolCallView, ...]): Generic envelope, one per invocation.
        risk (RiskScoreView | None): Risk outcome when the chain scored risk.
        test_cases (TestCasesView | None): Generated cases when the chain ran them.
        markdown (str): Exported Markdown when the chain exported it.
    """

    summary: str
    calls: tuple[ToolCallView, ...]
    risk: RiskScoreView | None = None
    test_cases: TestCasesView | None = None
    markdown: str = ""


class _PackResponse(Protocol):
    summary: str
    outcomes: Sequence[object]


RetrieveHits = Callable[[str], Sequence[ScoredChunk]]
Orchestrate = Callable[..., _PackResponse]


class SoftwareDeliveryToolRunner(Protocol):
    """Run the Software Delivery tool chain over freshly retrieved evidence."""

    def run(
        self,
        target: str,
        *,
        generate_tests: bool = True,
        output_style: str = "steps",
    ) -> SoftwareDeliveryRunView:
        """Retrieve evidence for ``target``, run the chain, and project the result."""


class PackSoftwareDeliveryTools:
    """Adapter from lazily-wired pack callables to the composition Protocol."""

    def __init__(
        self,
        *,
        retrieve: RetrieveHits,
        invoke: OpaqueInvoke,
        orchestrate: Orchestrate,
    ) -> None:
        self._retrieve = retrieve
        self._invoke = invoke
        self._orchestrate = orchestrate

    def run(
        self,
        target: str,
        *,
        generate_tests: bool = True,
        output_style: str = "steps",
    ) -> SoftwareDeliveryRunView:
        if output_style not in SOFTWARE_DELIVERY_TEST_STYLES:
            raise ApplicationValidationError(
                "output_style must be one of "
                f"{sorted(SOFTWARE_DELIVERY_TEST_STYLES)}"
            )
        hits = require_evidence(self._retrieve(target))
        recorder = ToolCallRecorder(self._invoke)
        try:
            response = self._orchestrate(
                target=target,
                hits=hits,
                generate_tests=generate_tests,
                output_style=output_style,
                invoke=recorder,
            )
        except (DomainValidationError, RuntimeError) as error:
            raise ToolRunFailedError(
                _TOOL_RUN_FAILED_MESSAGE, calls=recorder.calls
            ) from error
        return run_view(response, recorder.calls)


def software_delivery_tools_enabled(settings: Settings) -> bool:
    """Whether the pack behind the tool-run surface is enabled.

    Composition names the pack *id* — a configuration value read out of
    settings, not an import. Presentation asks this rather than catching
    ``ConfigurationError``, which also means "your credentials are missing".
    """
    return _PACK_ID in settings.domain_tools.enabled_packs


def require_evidence(hits: Sequence[ScoredChunk]) -> tuple[ScoredChunk, ...]:
    """Return ``hits``, or refuse the run when nothing cleared the threshold.

    Lives here rather than in ``container.py`` so the guard is unit-testable
    offline, and so the container keeps exactly one ``InsufficientEvidenceError``
    translation — an invariant asserted by
    ``test_insufficient_evidence_translation_is_singular_at_composition_edge``.
    """
    evidence = tuple(hits)
    if not evidence:
        raise InsufficientEvidenceError(_NO_EVIDENCE_MESSAGE)
    return evidence


def _risk_view(assessment: object) -> RiskScoreView:
    return RiskScoreView(
        score=assessment.score,  # type: ignore[attr-defined]
        level=assessment.level,  # type: ignore[attr-defined]
        rationale=assessment.rationale,  # type: ignore[attr-defined]
        factors=tuple(
            RiskFactorView(
                factor_id=factor.factor_id,
                weight=factor.weight,
                references=tuple(factor.references),
            )
            for factor in assessment.factors  # type: ignore[attr-defined]
        ),
    )


def _test_cases_view(result: object) -> TestCasesView:
    return TestCasesView(
        output_style=result.output_style,  # type: ignore[attr-defined]
        cases=tuple(
            TestCaseView(
                title=case.title,
                steps=tuple(case.steps),
                expected=case.expected,
                references=tuple(case.references),
            )
            for case in result.test_cases  # type: ignore[attr-defined]
        ),
    )


def run_view(
    response: _PackResponse,
    calls: Sequence[ToolCallView],
) -> SoftwareDeliveryRunView:
    """Project a pack orchestration response onto composition views."""
    risk: RiskScoreView | None = None
    test_cases: TestCasesView | None = None
    markdown = ""
    for outcome in response.outcomes:
        assessment = getattr(outcome, "assessment", None)
        if assessment is not None:
            risk = _risk_view(assessment)
            continue
        generation = getattr(outcome, "result", None)
        if generation is not None:
            test_cases = _test_cases_view(generation)
            continue
        exported = getattr(outcome, "markdown", None)
        if exported is not None:
            markdown = exported
            continue
        raise ToolRunFailedError(_UNKNOWN_OUTCOME_MESSAGE, calls=tuple(calls))
    return SoftwareDeliveryRunView(
        summary=response.summary,
        calls=tuple(calls),
        risk=risk,
        test_cases=test_cases,
        markdown=markdown,
    )
