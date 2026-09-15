"""Always-mounted test-design draft routes."""

from __future__ import annotations

from fastapi import APIRouter

from composition.test_design import (
    CreateTestDesignDraftRequest as CreateDraftFacadeRequest,
    PatchTestDesignDraftRequest as PatchDraftFacadeRequest,
    SourceLocatorView,
    SourceReferenceView,
    TestCandidateView,
)
from presentation.http.deps import TestDesignFacadeDep
from presentation.http.errors import problem_responses
from presentation.http.schemas import (
    CreateTestDesignDraftRequest,
    ExpectedVersionRequest,
    ExportTestDesignGoogleDriveRequest,
    ExportTestDesignGoogleDriveResponse,
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
    """Save draft selection, title edits, and manual candidate adds."""
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
    view = facade.patch_draft(
        draft_id,
        PatchDraftFacadeRequest(
            expected_version=body.expected_version,
            candidates=candidates,
        ),
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


@router.post(
    "/drafts/{draft_id}/export/google-drive",
    responses=problem_responses(404, 405, 409, 422, 500),
)
def export_draft_google_drive(
    draft_id: str,
    body: ExportTestDesignGoogleDriveRequest,
    facade: TestDesignFacadeDep,
) -> ExportTestDesignGoogleDriveResponse:
    """Export selected titles into a user-chosen Google Drive folder."""
    receipt = facade.export_to_google_drive(
        draft_id,
        folder_id=body.folder_id,
        file_name=body.file_name,
    )
    return ExportTestDesignGoogleDriveResponse(
        file_id=receipt.file_id,
        file_name=receipt.file_name,
    )
