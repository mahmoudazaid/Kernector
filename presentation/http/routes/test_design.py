"""Always-mounted test-design draft routes."""

from __future__ import annotations

from fastapi import APIRouter

from composition.test_design.facade import (
    CreateTestDesignDraftRequest as CreateDraftFacadeRequest,
    GenerateTestDesignCasesRequest as GenerateCasesFacadeRequest,
    GeneratedTestCaseView,
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
    GenerateTestDesignCasesRequest,
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
    """Save draft selection, title edits, types, and generated case edits."""
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
                test_type=item.test_type,  # type: ignore[arg-type]
            )
            for item in body.candidates
        )
    generated_cases = None
    if body.generated_cases is not None:
        generated_cases = tuple(
            GeneratedTestCaseView(
                candidate_id=item.candidate_id,
                test_type=item.test_type,  # type: ignore[arg-type]
                automation_fit=item.automation_fit,  # type: ignore[arg-type]
                automation_rationale=item.automation_rationale,
                availability=item.availability,  # type: ignore[arg-type]
                preconditions=item.preconditions,
                steps=tuple(item.steps),
                expected_result=item.expected_result,
                gherkin=item.gherkin,
                user_edited=item.user_edited,
            )
            for item in body.generated_cases
        )
    view = facade.patch_draft(
        draft_id,
        PatchDraftFacadeRequest(
            expected_version=body.expected_version,
            candidates=candidates,
            generated_cases=generated_cases,
            cucumber_feature=body.cucumber_feature,
            cucumber_background=body.cucumber_background,
        ),
    )
    return test_coverage_draft_response(view)


@router.post(
    "/drafts/{draft_id}/confirm",
    responses=problem_responses(404, 405, 409, 422, 500, 502),
)
def confirm_draft(
    draft_id: str,
    body: ExpectedVersionRequest,
    facade: TestDesignFacadeDep,
) -> TestCoverageDraftResponse:
    """Mark coverage selection ready; no-op when already ready/case_editing."""
    view = facade.confirm_draft(
        draft_id, expected_version=body.expected_version
    )
    return test_coverage_draft_response(view)


@router.post(
    "/drafts/{draft_id}/generate",
    responses=problem_responses(404, 405, 409, 422, 500, 502),
)
def generate_cases(
    draft_id: str,
    body: GenerateTestDesignCasesRequest,
    facade: TestDesignFacadeDep,
) -> TestCoverageDraftResponse:
    """Generate detailed manual/Cucumber cases for selected candidates."""
    overrides = ()
    if body.type_overrides is not None:
        overrides = tuple(
            (item.candidate_id, item.test_type)  # type: ignore[misc]
            for item in body.type_overrides
        )
    view = facade.generate_cases(
        draft_id,
        GenerateCasesFacadeRequest(
            expected_version=body.expected_version,
            candidate_ids=(
                tuple(body.candidate_ids) if body.candidate_ids is not None else None
            ),
            type_overrides=overrides,  # type: ignore[arg-type]
            overwrite_edited=body.overwrite_edited,
        ),
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
        destination_label=body.destination_label,
    )
    return ExportTestDesignGoogleDriveResponse(
        file_id=receipt.file_id,
        file_name=receipt.file_name,
    )
