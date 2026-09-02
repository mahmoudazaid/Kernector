"""Composition-facing types and adapter for requirements analysis."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from application.citations import build_citations
from application.contracts import Citation
from domain.knowledge import ScoredChunk, SourceReference
from domain.models import AskResult
from infrastructure.config import Settings

_REQUIREMENTS_ANALYSIS_PACK_ID = "software-delivery"


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
    ask_result: AskResult | None = None


class RequirementsAnalyzer(Protocol):
    """Analyze pasted requirements against multi-source retrieved evidence."""

    def analyze(self, requirements: str) -> RequirementsAnalysisView:
        """Run retrieval-backed analysis and return a typed structured result."""


class _PackFinding(Protocol):
    statement: str
    references: Sequence[SourceReference]


class _PackAnalysisResult(Protocol):
    summary: str
    acceptance_criteria_gaps: Sequence[_PackFinding]
    risks: Sequence[_PackFinding]
    clarification_questions: Sequence[_PackFinding]
    evidence: Sequence[ScoredChunk]
    ask_result: AskResult | None


ExecuteRequirementsAnalysis = Callable[[str], _PackAnalysisResult]


def analysis_citations(view: RequirementsAnalysisView) -> tuple[Citation, ...]:
    """Project analysis evidence onto generic application Citation values."""
    return build_citations(view.evidence)


def _finding_bullets(
    findings: Sequence[RequirementsAnalysisFindingView],
) -> tuple[str, ...]:
    return tuple(
        f"- {finding.statement} — "
        + ", ".join(
            f"`{ref.source_id}` ({ref.source_type})" for ref in finding.references
        )
        for finding in findings
    )


def format_requirements_analysis_answer(view: RequirementsAnalysisView) -> str:
    """Render a chat reply from a structured requirements-analysis view."""
    sections = [view.summary]
    for title, findings in (
        ("Acceptance criteria gaps", view.acceptance_criteria_gaps),
        ("Risks", view.risks),
        ("Clarification questions", view.clarification_questions),
    ):
        bullets = _finding_bullets(findings)
        if not bullets:
            continue
        sections.append(f"**{title}**")
        sections.extend(bullets)
    return "\n\n".join(sections)


def _finding_views(
    findings: Sequence[_PackFinding],
) -> tuple[RequirementsAnalysisFindingView, ...]:
    return tuple(
        RequirementsAnalysisFindingView(
            finding.statement,
            tuple(finding.references),
        )
        for finding in findings
    )


def _to_view(result: _PackAnalysisResult) -> RequirementsAnalysisView:
    return RequirementsAnalysisView(
        summary=result.summary,
        acceptance_criteria_gaps=_finding_views(result.acceptance_criteria_gaps),
        risks=_finding_views(result.risks),
        clarification_questions=_finding_views(result.clarification_questions),
        evidence=tuple(result.evidence),
        ask_result=getattr(result, "ask_result", None),
    )


class PackRequirementsAnalyzer:
    """Adapter from the lazy-loaded pack executor to the composition Protocol."""

    def __init__(self, execute: ExecuteRequirementsAnalysis) -> None:
        self._execute = execute

    def analyze(self, requirements: str) -> RequirementsAnalysisView:
        return _to_view(self._execute(requirements))


def requirements_analysis_enabled(settings: Settings) -> bool:
    """Whether requirements analysis is wired for the current runtime settings."""
    return _REQUIREMENTS_ANALYSIS_PACK_ID in settings.domain_tools.enabled_packs
