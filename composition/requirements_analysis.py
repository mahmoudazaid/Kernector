"""Composition-facing types and adapter for requirements analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from application.citations import build_citations
from application.contracts import Citation
from domain.knowledge import ScoredChunk, SourceReference


@dataclass(frozen=True, slots=True)
class RequirementsAnalysisFindingView:
    """One cited finding exposed at the composition boundary."""

    statement: str
    references: tuple[SourceReference, ...]


@dataclass(frozen=True, slots=True)
class RequirementsAnalysisView:
    """Structured requirements analysis result for presentation and composition."""

    summary: str
    acceptance_criteria_gaps: tuple[RequirementsAnalysisFindingView, ...]
    risks: tuple[RequirementsAnalysisFindingView, ...]
    clarification_questions: tuple[RequirementsAnalysisFindingView, ...]
    evidence: tuple[ScoredChunk, ...]


class RequirementsAnalyzer(Protocol):
    """Analyze pasted requirements against multi-source retrieved evidence."""

    def analyze(self, requirements: str) -> RequirementsAnalysisView:
        """Run retrieval-backed analysis and return a typed structured result."""


def analysis_citations(view: RequirementsAnalysisView) -> tuple[Citation, ...]:
    """Project analysis evidence onto generic application Citation values."""
    return build_citations(view.evidence)


def _finding_views(
    findings: Sequence[object],
) -> tuple[RequirementsAnalysisFindingView, ...]:
    return tuple(
        RequirementsAnalysisFindingView(
            finding.statement,  # type: ignore[attr-defined]
            tuple(finding.references),  # type: ignore[attr-defined]
        )
        for finding in findings
    )


def _to_view(result: object) -> RequirementsAnalysisView:
    return RequirementsAnalysisView(
        summary=result.summary,  # type: ignore[attr-defined]
        acceptance_criteria_gaps=_finding_views(
            result.acceptance_criteria_gaps  # type: ignore[attr-defined]
        ),
        risks=_finding_views(result.risks),  # type: ignore[attr-defined]
        clarification_questions=_finding_views(
            result.clarification_questions  # type: ignore[attr-defined]
        ),
        evidence=tuple(result.evidence),  # type: ignore[attr-defined]
    )


class PackRequirementsAnalyzer:
    """Adapter from the lazy-loaded pack use case to the composition Protocol."""

    def __init__(self, use_case: object) -> None:
        self._use_case = use_case

    def analyze(self, requirements: str) -> RequirementsAnalysisView:
        from packs.software_delivery.requirements_analysis_contracts import (
            AnalyzeRequirementsRequest,
        )

        result = self._use_case.execute(AnalyzeRequirementsRequest(requirements))
        return _to_view(result)
