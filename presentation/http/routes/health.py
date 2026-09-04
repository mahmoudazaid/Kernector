"""Unversioned operational health route."""

from fastapi import APIRouter

from presentation.http.errors import problem_responses
from presentation.http.schemas import HealthResponse

router = APIRouter(tags=["ops"])


@router.get(
    "/health",
    responses=problem_responses(405),
)
def health() -> HealthResponse:
    """Return process readiness without touching composition or infrastructure."""
    return HealthResponse(status="ok")
