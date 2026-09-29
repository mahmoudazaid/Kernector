"""Read-side Test Design draft views shared by composition and pack tools."""

from __future__ import annotations

from dataclasses import dataclass

from packs.software_delivery.test_design.models import (
    AutomationFit,
    CandidateOrigin,
    CaseAvailability,
    CoverageCategory,
    DraftStatus,
    TestCaseType,
)


@dataclass(frozen=True, slots=True)
class SourceLocatorView:
    provider: str
    locator: str


@dataclass(frozen=True, slots=True)
class SourceReferenceView:
    source_id: str
    source_type: str


@dataclass(frozen=True, slots=True)
class TestCandidateView:
    __test__ = False

    candidate_id: str
    title: str
    category: CoverageCategory
    rationale: str
    evidence_references: tuple[SourceReferenceView, ...]
    selected: bool
    origin: CandidateOrigin
    test_type: TestCaseType | None = None


@dataclass(frozen=True, slots=True)
class GeneratedTestCaseView:
    __test__ = False

    candidate_id: str
    test_type: TestCaseType
    automation_fit: AutomationFit
    automation_rationale: str
    availability: CaseAvailability
    preconditions: str
    steps: tuple[str, ...]
    expected_result: str
    gherkin: str
    user_edited: bool


@dataclass(frozen=True, slots=True)
class TestCoverageDraftView:
    __test__ = False

    draft_id: str
    workspace_id: str
    conversation_id: str
    source_reference: SourceReferenceView
    ticket_identifier: str
    status: DraftStatus
    candidates: tuple[TestCandidateView, ...]
    version: int
    selected_candidate_ids: tuple[str, ...]
    generated_cases: tuple[GeneratedTestCaseView, ...] = ()
    evidence_fingerprint: str | None = None
    skipped_edited_candidate_ids: tuple[str, ...] = ()
    cucumber_feature: str = ""
    cucumber_background: str = ""
