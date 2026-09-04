"""Unversioned operational health route."""

from fastapi import APIRouter

from presentation.http.schemas import HealthResponse
from presentation.http.errors import Problem

router = APIRouter(tags=["ops"])

_PROBLEM_RESPONSES = {
    404: {"model": Problem, "description": "Not found"},
    422: {"model": Problem, "description": "Validation error"},
    500: {"model": Problem, "description": "Server error"},
}


@router.get(
    "/health",
    response_model=HealthResponse,
    responses=_PROBLEM_RESPONSES,
)
def health() -> HealthResponse:
    """Return process readiness without touching composition or infrastructure."""
    return HealthResponse(status="ok")
