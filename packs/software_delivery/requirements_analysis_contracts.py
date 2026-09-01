"""Pack-local contracts for Software Delivery requirements analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar

from domain.knowledge import ScoredChunk, SourceReference
from packs.software_delivery.errors import RequirementsAnalysisValidationError
from packs.software_delivery.limits import (
    MAX_ANALYSIS_ANSWER_CHARS,
    MAX_ANALYSIS_FINDINGS,
    MAX_FINDING_STATEMENT_CHARS,
    MAX_REQUIREMENTS_CHARS,
)

ANALYSIS_CATEGORIES = frozenset({"gap", "risk", "clarification", "ambiguity"})
AnalysisCategory = Literal["gap", "risk", "clarification", "ambiguity"]

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
    """One structured finding from requirements analysis."""

    category: str
    statement: str
    references: Sequence[SourceReference]

    def __post_init__(self) -> None:
        # Structural checks only; callers that interpret model output must map
        # failures to ToolFailureError, never RequirementsAnalysisValidationError.
        if not isinstance(self.category, str) or self.category not in ANALYSIS_CATEGORIES:
            raise ValueError(
                f"category must be one of {sorted(ANALYSIS_CATEGORIES)}, "
                f"got {self.category!r}"
            )
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

    answer: str
    findings: Sequence[RequirementsFinding]
    evidence: Sequence[ScoredChunk]

    def __post_init__(self) -> None:
        if not isinstance(self.answer, str) or not self.answer.strip():
            raise ValueError("answer must be non-empty")
        if len(self.answer) > MAX_ANALYSIS_ANSWER_CHARS:
            raise ValueError(
                f"answer must be at most {MAX_ANALYSIS_ANSWER_CHARS} characters"
            )
        findings = _require_sequence(self.findings, "findings", ValueError)
        if len(findings) == 0:
            raise ValueError("findings must be non-empty")
        if len(findings) > MAX_ANALYSIS_FINDINGS:
            raise ValueError(
                f"findings must have at most {MAX_ANALYSIS_FINDINGS} items"
            )
        normalized_findings: list[RequirementsFinding] = []
        for finding in findings:
            if not isinstance(finding, RequirementsFinding):
                raise ValueError(
                    f"findings items must be RequirementsFinding, got {finding!r}"
                )
            normalized_findings.append(finding)
        object.__setattr__(self, "findings", tuple(normalized_findings))

        evidence = _require_sequence(self.evidence, "evidence", ValueError)
        normalized_evidence: list[ScoredChunk] = []
        for hit in evidence:
            if not isinstance(hit, ScoredChunk):
                raise ValueError(
                    f"evidence items must be ScoredChunk, got {hit!r}"
                )
            normalized_evidence.append(hit)
        object.__setattr__(self, "evidence", tuple(normalized_evidence))
