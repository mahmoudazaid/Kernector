"""Composition-facing DTOs and facade for the test-design workflow."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from application.errors import InsufficientEvidenceError
from composition.software_delivery_tools import software_delivery_tools_enabled
from composition.test_design_errors import (
    TestDesignNotFoundError,
    TestDesignUnavailableError,
    TestDesignValidationError,
    TestDesignVersionConflictError,
)
from domain.knowledge import ScoredChunk, SourceReference
from infrastructure.config import Settings
from infrastructure.workspace_store.errors import (
    VersionedStoreNotFoundError,
    VersionedStoreVersionConflictError,
)

DraftStatus = Literal["coverage_review", "scenario_editing", "ready"]
CandidateOrigin = Literal["suggested", "manual"]
CoverageCategory = Literal[
    "happy_path",
    "negative",
    "edge_case",
    "integration",
    "permission_security",
    "failure_recovery",
]

RetrieveHits = Callable[[str], Sequence[ScoredChunk]]


@dataclass(frozen=True, slots=True)
class SourceReferenceView:
    source_id: str
    source_type: str


@dataclass(frozen=True, slots=True)
class CoverageGapView:
    category: CoverageCategory
    detail: str


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


@dataclass(frozen=True, slots=True)
class TestScenarioView:
    __test__ = False

    scenario_id: str
    candidate_id: str
    title: str
    category: CoverageCategory
    preconditions: tuple[str, ...]
    steps: tuple[str, ...]
    expected_result: str
    evidence_references: tuple[SourceReferenceView, ...]


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
    scenarios: tuple[TestScenarioView, ...]
    coverage_gaps: tuple[CoverageGapView, ...]
    version: int
    selected_candidate_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CreateTestDesignDraftRequest:
    conversation_id: str
    source_reference: SourceReferenceView
    ticket_identifier: str


@dataclass(frozen=True, slots=True)
class PatchTestDesignDraftRequest:
    expected_version: int
    candidates: tuple[TestCandidateView, ...] | None = None
    scenarios: tuple[TestScenarioView, ...] | None = None


@dataclass(frozen=True, slots=True)
class ChatWorkflowActionView:
    """Pack-agnostic chat handoff action for the wire."""

    kind: Literal["start_workflow", "open_workflow"]
    workflow_id: str
    label: str
    source_reference: SourceReferenceView | None = None
    ticket_identifier: str | None = None
    draft_id: str | None = None


def resolve_start_test_design_action(
    *,
    settings: Settings,
    source_reference: SourceReferenceView | None,
    ticket_identifier: str | None,
) -> ChatWorkflowActionView | None:
    """Return a Start Test Design action when pack is on and context is explicit."""
    if not software_delivery_tools_enabled(settings):
        return None
    if source_reference is None or ticket_identifier is None:
        return None
    ticket = ticket_identifier.strip()
    if not ticket or ticket.isdigit():
        return None
    if not source_reference.source_id.strip() or not source_reference.source_type.strip():
        return None
    return ChatWorkflowActionView(
        kind="start_workflow",
        workflow_id="software-delivery.test-design",
        label="Start Test Design",
        source_reference=source_reference,
        ticket_identifier=ticket,
    )


class TestDesignFacade:
    """HTTP-facing facade: pack gate, lazy pack import, store bridge."""

    def __init__(
        self,
        *,
        settings: Settings,
        retrieve: RetrieveHits,
        store_path: Path,
        workspace_id: str,
    ) -> None:
        self._settings = settings
        self._retrieve = retrieve
        self._store_path = store_path
        self._workspace_id = workspace_id
        self._repo = None

    def create_draft(
        self, request: CreateTestDesignDraftRequest
    ) -> TestCoverageDraftView:
        self._require_enabled()
        draft_id = str(uuid.uuid4())
        PlanCoverage, PlanCoverageRequest, CoverageEvidenceItem = (
            self._load_plan_coverage()
        )
        ticket = _require_ticket(request.ticket_identifier)
        source = _require_source(request.source_reference)
        hits = self._retrieve(ticket)
        preferred = tuple(
            hit
            for hit in hits
            if hit.chunk.reference.source_id == source.source_id
            and hit.chunk.reference.source_type == source.source_type
        )
        selected_hits = preferred or tuple(hits)
        evidence = tuple(
            CoverageEvidenceItem(
                reference=hit.chunk.reference,
                text=hit.chunk.content,
            )
            for hit in selected_hits
            if hit.chunk.content.strip()
        )
        if not evidence:
            raise InsufficientEvidenceError(
                "No usable grounded evidence for test coverage planning."
            )
        chat_model = self._build_chat_model()
        repo = self._repository()
        use_case = PlanCoverage(chat_model=chat_model, repository=repo)
        try:
            draft = use_case.execute(
                PlanCoverageRequest(
                    draft_id=draft_id,
                    workspace_id=self._workspace_id,
                    conversation_id=_require_text(
                        request.conversation_id, "conversation_id"
                    ),
                    source_reference=SourceReference(
                        source.source_id, source.source_type
                    ),
                    ticket_identifier=ticket,
                    evidence=evidence,
                )
            )
        except Exception as error:
            from packs.software_delivery.test_design.plan_coverage import (
                TestDesignInsufficientEvidenceError,
            )

            if isinstance(error, TestDesignInsufficientEvidenceError):
                raise InsufficientEvidenceError(str(error)) from error
            raise
        return _draft_view(draft)

    def get_draft(self, draft_id: str) -> TestCoverageDraftView:
        self._require_enabled()
        draft = self._repository().get(draft_id)
        if draft is None:
            raise TestDesignNotFoundError("draft not found")
        return _draft_view(draft)

    def patch_draft(
        self, draft_id: str, request: PatchTestDesignDraftRequest
    ) -> TestCoverageDraftView:
        self._require_enabled()
        TestCandidate, TestScenario, TestCoverageDraft, _CoverageGap = (
            self._load_models()
        )
        repo = self._repository()
        current = repo.get(draft_id)
        if current is None:
            raise TestDesignNotFoundError("draft not found")
        candidates = current.candidates
        scenarios = current.scenarios
        if request.candidates is not None:
            candidates = tuple(
                TestCandidate(
                    candidate_id=item.candidate_id,
                    title=item.title,
                    category=item.category,
                    rationale=item.rationale,
                    evidence_references=tuple(
                        SourceReference(ref.source_id, ref.source_type)
                        for ref in item.evidence_references
                    ),
                    selected=item.selected,
                    origin=item.origin,
                )
                for item in request.candidates
            )
        if request.scenarios is not None:
            scenarios = tuple(
                TestScenario(
                    scenario_id=item.scenario_id,
                    candidate_id=item.candidate_id,
                    title=item.title,
                    category=item.category,
                    preconditions=item.preconditions,
                    steps=item.steps,
                    expected_result=item.expected_result,
                    evidence_references=tuple(
                        SourceReference(ref.source_id, ref.source_type)
                        for ref in item.evidence_references
                    ),
                )
                for item in request.scenarios
            )
        status = current.status
        if request.scenarios is not None and scenarios:
            status = "scenario_editing"
        updated = TestCoverageDraft(
            draft_id=current.draft_id,
            workspace_id=current.workspace_id,
            conversation_id=current.conversation_id,
            source_reference=current.source_reference,
            ticket_identifier=current.ticket_identifier,
            status=status,
            candidates=candidates,
            scenarios=scenarios,
            coverage_gaps=current.coverage_gaps,
            version=current.version,
        )
        try:
            saved = repo.update(
                updated, expected_version=request.expected_version
            )
        except VersionedStoreNotFoundError as error:
            raise TestDesignNotFoundError("draft not found") from error
        except VersionedStoreVersionConflictError as error:
            raise TestDesignVersionConflictError("version conflict") from error
        return _draft_view(saved)

    def generate_scenarios(
        self, draft_id: str, *, expected_version: int
    ) -> TestCoverageDraftView:
        self._require_enabled()
        GenerateScenarios, GenerateScenariosRequest = self._load_generate()
        from packs.software_delivery.test_design.errors import (
            TestDesignValidationError as PackValidationError,
        )

        use_case = GenerateScenarios(
            chat_model=self._build_chat_model(),
            repository=self._repository(),
        )
        try:
            draft = use_case.execute(
                GenerateScenariosRequest(
                    draft_id=draft_id, expected_version=expected_version
                )
            )
        except PackValidationError as error:
            if "draft" in str(error).lower():
                raise TestDesignNotFoundError("draft not found") from error
            raise TestDesignValidationError(str(error)) from error
        except VersionedStoreNotFoundError as error:
            raise TestDesignNotFoundError("draft not found") from error
        except VersionedStoreVersionConflictError as error:
            raise TestDesignVersionConflictError("version conflict") from error
        return _draft_view(draft)

    def confirm_draft(
        self, draft_id: str, *, expected_version: int
    ) -> TestCoverageDraftView:
        self._require_enabled()
        _TestCandidate, _TestScenario, TestCoverageDraft, _CoverageGap = (
            self._load_models()
        )
        repo = self._repository()
        current = repo.get(draft_id)
        if current is None:
            raise TestDesignNotFoundError("draft not found")
        if current.status == "ready" and current.version == expected_version:
            return _draft_view(current)
        selected = {c.candidate_id for c in current.candidates if c.selected}
        scenario_ids = {s.candidate_id for s in current.scenarios}
        if selected - scenario_ids:
            raise TestDesignValidationError(
                "selected candidates must have scenarios before confirm"
            )
        updated = TestCoverageDraft(
            draft_id=current.draft_id,
            workspace_id=current.workspace_id,
            conversation_id=current.conversation_id,
            source_reference=current.source_reference,
            ticket_identifier=current.ticket_identifier,
            status="ready",
            candidates=current.candidates,
            scenarios=current.scenarios,
            coverage_gaps=current.coverage_gaps,
            version=current.version,
        )
        try:
            saved = repo.update(updated, expected_version=expected_version)
        except VersionedStoreNotFoundError as error:
            raise TestDesignNotFoundError("draft not found") from error
        except VersionedStoreVersionConflictError as error:
            raise TestDesignVersionConflictError("version conflict") from error
        return _draft_view(saved)

    def _require_enabled(self) -> None:
        if not software_delivery_tools_enabled(self._settings):
            raise TestDesignUnavailableError("test design unavailable")

    def _repository(self):
        if self._repo is None:
            from composition.test_design_store import (
                VersionedTestCoverageDraftRepository,
            )
            from infrastructure.workspace_store.sql_store import (
                VersionedWorkspaceStore,
            )

            store = VersionedWorkspaceStore(self._store_path, self._workspace_id)
            self._repo = VersionedTestCoverageDraftRepository(store)
        return self._repo

    def _build_chat_model(self):
        from composition.container import build_chat_model

        return build_chat_model(self._settings)

    @staticmethod
    def _load_plan_coverage():
        from packs.software_delivery.test_design.plan_coverage import (
            CoverageEvidenceItem,
            PlanCoverage,
            PlanCoverageRequest,
        )

        return PlanCoverage, PlanCoverageRequest, CoverageEvidenceItem

    @staticmethod
    def _load_generate():
        from packs.software_delivery.test_design.generate_scenarios import (
            GenerateScenarios,
            GenerateScenariosRequest,
        )

        return GenerateScenarios, GenerateScenariosRequest

    @staticmethod
    def _load_models():
        from packs.software_delivery.test_design.models import (
            CoverageGap,
            TestCandidate,
            TestCoverageDraft,
            TestScenario,
        )

        return TestCandidate, TestScenario, TestCoverageDraft, CoverageGap


def _draft_view(draft: object) -> TestCoverageDraftView:
    return TestCoverageDraftView(
        draft_id=draft.draft_id,  # type: ignore[attr-defined]
        workspace_id=draft.workspace_id,  # type: ignore[attr-defined]
        conversation_id=draft.conversation_id,  # type: ignore[attr-defined]
        source_reference=SourceReferenceView(
            source_id=draft.source_reference.source_id,  # type: ignore[attr-defined]
            source_type=draft.source_reference.source_type,  # type: ignore[attr-defined]
        ),
        ticket_identifier=draft.ticket_identifier,  # type: ignore[attr-defined]
        status=draft.status,  # type: ignore[attr-defined]
        candidates=tuple(
            TestCandidateView(
                candidate_id=item.candidate_id,
                title=item.title,
                category=item.category,
                rationale=item.rationale,
                evidence_references=tuple(
                    SourceReferenceView(ref.source_id, ref.source_type)
                    for ref in item.evidence_references
                ),
                selected=item.selected,
                origin=item.origin,
            )
            for item in draft.candidates  # type: ignore[attr-defined]
        ),
        scenarios=tuple(
            TestScenarioView(
                scenario_id=item.scenario_id,
                candidate_id=item.candidate_id,
                title=item.title,
                category=item.category,
                preconditions=tuple(item.preconditions),
                steps=tuple(item.steps),
                expected_result=item.expected_result,
                evidence_references=tuple(
                    SourceReferenceView(ref.source_id, ref.source_type)
                    for ref in item.evidence_references
                ),
            )
            for item in draft.scenarios  # type: ignore[attr-defined]
        ),
        coverage_gaps=tuple(
            CoverageGapView(category=gap.category, detail=gap.detail)
            for gap in draft.coverage_gaps  # type: ignore[attr-defined]
        ),
        version=draft.version,  # type: ignore[attr-defined]
        selected_candidate_ids=tuple(draft.selected_candidate_ids),  # type: ignore[attr-defined]
    )


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TestDesignValidationError(f"{field_name} must be non-empty")
    return value.strip()


def _require_ticket(value: object) -> str:
    text = _require_text(value, "ticket_identifier")
    if text.isdigit():
        raise TestDesignValidationError(
            "ticket_identifier must not be a bare number"
        )
    return text


def _require_source(value: SourceReferenceView) -> SourceReferenceView:
    if not isinstance(value, SourceReferenceView):
        raise TestDesignValidationError("source_reference is required")
    _require_text(value.source_id, "source_id")
    _require_text(value.source_type, "source_type")
    return value
