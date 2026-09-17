"""HTTP routes for response feedback collection (#219)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response

from application.submit_response_feedback import (
    ClearFeedbackRequest,
    GetFeedbackRequest,
    UpsertFeedbackRequest,
)
from presentation.http.deps import (
    ClearResponseFeedbackDep,
    GetResponseFeedbackDep,
    SubmitResponseFeedbackDep,
)
from presentation.http.errors import problem_responses
from presentation.http.schemas import (
    ResponseFeedbackResponse,
    UpsertResponseFeedbackRequest,
    response_feedback_response,
)

router = APIRouter(prefix="/api/v1", tags=["feedback"])


@router.get(
    "/responses/{request_id}/feedback",
    responses=problem_responses(404, 405, 422, 500),
)
def get_feedback(
    request_id: str,
    use_case: GetResponseFeedbackDep,
) -> ResponseFeedbackResponse:
    """Return the rating for ``request_id`` in the bound workspace."""
    stored = use_case.execute(GetFeedbackRequest(request_id=request_id))
    return response_feedback_response(stored)


@router.put(
    "/responses/{request_id}/feedback",
    responses=problem_responses(405, 422, 500),
)
def upsert_feedback(
    request_id: str,
    body: UpsertResponseFeedbackRequest,
    use_case: SubmitResponseFeedbackDep,
    conversation_id: str | None = Query(default=None),
    client_message_id: str | None = Query(default=None),
) -> ResponseFeedbackResponse:
    """Create or update the rating for ``request_id`` in the bound workspace."""
    stored = use_case.execute(
        UpsertFeedbackRequest(
            request_id=request_id,
            rating=body.rating,
            reason=body.reason,
            comment=body.comment,
            conversation_id=conversation_id,
            client_message_id=client_message_id,
        )
    )
    return response_feedback_response(stored)


@router.delete(
    "/responses/{request_id}/feedback",
    status_code=204,
    responses=problem_responses(404, 405, 422, 500),
)
def delete_feedback(
    request_id: str,
    use_case: ClearResponseFeedbackDep,
) -> Response:
    """Clear the rating for ``request_id`` in the bound workspace."""
    use_case.execute(ClearFeedbackRequest(request_id=request_id))
    return Response(status_code=204)
