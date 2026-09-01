"""Pack-local contracts for Software Delivery requirements analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeVar

from domain.knowledge import ScoredChunk, SourceReference
from packs.software_delivery.errors import RequirementsAnalysisValidationError
from packs.software_delivery.limits import (
    MAX_ANALYSIS_SUMMARY_CHARS,
    MAX_FINDINGS_PER_SECTION,
    MAX_FINDING_STATEMENT_CHARS,
    MAX_REQUIREMENTS_CHARS,
)

_E = TypeVar("_E", bound=Exception)


def _require_text(
    value: object,
    field_name: str,
    error_type: type[_E] = RequirementsAnalysisValidationError,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"{field_name} must be non-empty")
    return value


def _require_bounded_text(
    value: object,
    field_name: str,
    max_chars: int,
    error_type: type[_E] = RequirementsAnalysisValidationError,
) -> str:
    text = _require_text(value, field_name, error_type)
    if len(text) > max_chars:
        raise error_type(
            f"{field_name} must be at most {max_chars} characters, got {len(text)}"
        )
    return text


def _require_sequence(
    value: object,
    field_name: str,
    error_type: type[_E] = RequirementsAnalysisValidationError,
) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise error_type(f"{field_name} must be a sequence, got {value!r}")
    return value


def _sorted_references(
    references: Sequence[SourceReference],
) -> tuple[SourceReference, ...]:
    return tuple(
        sorted(references, key=lambda ref: (ref.source_type, ref.source_id))
    )


@dataclass(frozen=True, slots=True)
class AnalyzeRequirementsRequest:
    """Input for analyzing pasted requirements against retrieved evidence."""

    requirements: str

    def __post_init__(self) -> None:
        _require_bounded_text(
            self.requirements, "requirements", MAX_REQUIREMENTS_CHARS
        )


@dataclass(frozen=True, slots=True)
class RequirementsFinding:
    """One structured finding with trusted provenance references."""

    statement: str
    references: Sequence[SourceReference]

    def __post_init__(self) -> None:
        # Structural checks only; callers that interpret model output must map
        # failures to ToolFailureError, never RequirementsAnalysisValidationError.
        if not isinstance(self.statement, str) or not self.statement.strip():
            raise ValueError("statement must be non-empty")
        if len(self.statement) > MAX_FINDING_STATEMENT_CHARS:
            raise ValueError(
                f"statement must be at most {MAX_FINDING_STATEMENT_CHARS} characters"
            )
        refs = _require_sequence(self.references, "references", ValueError)
        if len(refs) == 0:
            raise ValueError("references must be non-empty")
        normalized: list[SourceReference] = []
        for ref in refs:
            if not isinstance(ref, SourceReference):
                raise ValueError(
                    f"references items must be SourceReference, got {ref!r}"
                )
            normalized.append(ref)
        object.__setattr__(self, "references", _sorted_references(normalized))


@dataclass(frozen=True, slots=True)
class RequirementsAnalysisResult:
    """Structured outcome of requirements analysis with cited evidence chunks."""

    summary: str
    acceptance_criteria_gaps: Sequence[RequirementsFinding]
    risks: Sequence[RequirementsFinding]
    clarification_questions: Sequence[RequirementsFinding]
    evidence: Sequence[ScoredChunk]

    def __post_init__(self) -> None:
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ValueError("summary must be non-empty")
        if len(self.summary) > MAX_ANALYSIS_SUMMARY_CHARS:
            raise ValueError(
                f"summary must be at most {MAX_ANALYSIS_SUMMARY_CHARS} characters"
            )
        object.__setattr__(
            self,
            "acceptance_criteria_gaps",
            _normalize_findings(self.acceptance_criteria_gaps, "acceptance_criteria_gaps"),
        )
        object.__setattr__(
            self,
            "risks",
            _normalize_findings(self.risks, "risks"),
        )
        object.__setattr__(
            self,
            "clarification_questions",
            _normalize_findings(self.clarification_questions, "clarification_questions"),
        )

        evidence = _require_sequence(self.evidence, "evidence", ValueError)
        normalized_evidence: list[ScoredChunk] = []
        for hit in evidence:
            if not isinstance(hit, ScoredChunk):
                raise ValueError(
                    f"evidence items must be ScoredChunk, got {hit!r}"
                )
            normalized_evidence.append(hit)
        object.__setattr__(self, "evidence", tuple(normalized_evidence))


def _normalize_findings(
    findings: object,
    field_name: str,
) -> tuple[RequirementsFinding, ...]:
    items = _require_sequence(findings, field_name, ValueError)
    if len(items) > MAX_FINDINGS_PER_SECTION:
        raise ValueError(
            f"{field_name} must have at most {MAX_FINDINGS_PER_SECTION} items"
        )
    normalized: list[RequirementsFinding] = []
    for item in items:
        if not isinstance(item, RequirementsFinding):
            raise ValueError(
                f"{field_name} items must be RequirementsFinding, got {item!r}"
            )
        normalized.append(item)
    return tuple(normalized)
