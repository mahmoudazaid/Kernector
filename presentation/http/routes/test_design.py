"""Always-mounted test-design draft routes."""

from __future__ import annotations

from fastapi import APIRouter

from composition.test_design import (
    CreateTestDesignDraftRequest as CreateDraftFacadeRequest,
    PatchTestDesignDraftRequest as PatchDraftFacadeRequest,
    SourceLocatorView,
    SourceReferenceView,
    TestCandidateView,
    TestScenarioView,
)
from presentation.http.deps import TestDesignFacadeDep
from presentation.http.errors import problem_responses
from presentation.http.schemas import (
    CreateTestDesignDraftRequest,
    ExpectedVersionRequest,
    PatchTestDesignDraftRequest,
    TestCoverageDraftResponse,
    test_coverage_draft_response,
)

router = APIRouter(prefix="/api/v1/test-design", tags=["test-design"])


@router.post(
    "/drafts",
    responses=problem_responses(404, 405, 409, 422, 500, 502),
)
def create_draft(
    body: CreateTestDesignDraftRequest,
    facade: TestDesignFacadeDep,
) -> TestCoverageDraftResponse:
    """Create a coverage-planning draft from a live GitHub Issue locator."""
    view = facade.create_draft(
        CreateDraftFacadeRequest(
            conversation_id=body.conversation_id,
            source_locator=SourceLocatorView(
                provider=body.source_locator.provider,
                locator=body.source_locator.locator,
            ),
        )
    )
    return test_coverage_draft_response(view)


@router.get(
    "/drafts/{draft_id}",
    responses=problem_responses(404, 405, 500),
)
def get_draft(
    draft_id: str,
    facade: TestDesignFacadeDep,
) -> TestCoverageDraftResponse:
    """Load a workspace-scoped test-design draft."""
    return test_coverage_draft_response(facade.get_draft(draft_id))


@router.patch(
    "/drafts/{draft_id}",
    responses=problem_responses(404, 405, 409, 422, 500),
)
def patch_draft(
    draft_id: str,
    body: PatchTestDesignDraftRequest,
    facade: TestDesignFacadeDep,
) -> TestCoverageDraftResponse:
    """Save draft selection, title edits, manual adds, and scenario edits."""
    candidates = None
    if body.candidates is not None:
        candidates = tuple(
            TestCandidateView(
                candidate_id=item.candidate_id,
                title=item.title,
                category=item.category,  # type: ignore[arg-type]
                rationale=item.rationale,
                evidence_references=tuple(
                    SourceReferenceView(ref.source_id, ref.source_type)
                    for ref in item.evidence_references
                ),
                selected=item.selected,
                origin=item.origin,  # type: ignore[arg-type]
            )
            for item in body.candidates
        )
    scenarios = None
    if body.scenarios is not None:
        scenarios = tuple(
            TestScenarioView(
                scenario_id=item.scenario_id,
                candidate_id=item.candidate_id,
                title=item.title,
                category=item.category,  # type: ignore[arg-type]
                preconditions=tuple(item.preconditions),
                steps=tuple(item.steps),
                expected_result=item.expected_result,
                evidence_references=tuple(
                    SourceReferenceView(ref.source_id, ref.source_type)
                    for ref in item.evidence_references
                ),
            )
            for item in body.scenarios
        )
    view = facade.patch_draft(
        draft_id,
        PatchDraftFacadeRequest(
            expected_version=body.expected_version,
            candidates=candidates,
            scenarios=scenarios,
        ),
    )
    return test_coverage_draft_response(view)


@router.post(
    "/drafts/{draft_id}/scenarios",
    responses=problem_responses(404, 405, 409, 422, 500, 502),
)
def generate_scenarios(
    draft_id: str,
    body: ExpectedVersionRequest,
    facade: TestDesignFacadeDep,
) -> TestCoverageDraftResponse:
    """Generate scenarios for selected candidates that are still missing them."""
    view = facade.generate_scenarios(
        draft_id, expected_version=body.expected_version
    )
    return test_coverage_draft_response(view)


@router.post(
    "/drafts/{draft_id}/confirm",
    responses=problem_responses(404, 405, 409, 422, 500),
)
def confirm_draft(
    draft_id: str,
    body: ExpectedVersionRequest,
    facade: TestDesignFacadeDep,
) -> TestCoverageDraftResponse:
    """Mark the draft ready; idempotent when already ready at matching version."""
    view = facade.confirm_draft(
        draft_id, expected_version=body.expected_version
    )
    return test_coverage_draft_response(view)
