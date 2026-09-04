"""Versioned capabilities prove-out route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from composition import Settings, available_providers, software_delivery_tools_enabled
from presentation.http.deps import get_settings
from presentation.http.errors import Problem
from presentation.http.schemas import CapabilitiesResponse

router = APIRouter(prefix="/api/v1", tags=["capabilities"])

_PROBLEM_RESPONSES = {
    404: {"model": Problem, "description": "Not found"},
    422: {"model": Problem, "description": "Validation error"},
    500: {"model": Problem, "description": "Server error"},
    502: {"model": Problem, "description": "Provider error"},
}


@router.get(
    "/capabilities",
    response_model=CapabilitiesResponse,
    responses=_PROBLEM_RESPONSES,
)
def capabilities(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CapabilitiesResponse:
    """Expose buildable providers and tool-pack enablement via composition."""
    return CapabilitiesResponse(
        providers=list(available_providers()),
        default_provider=settings.provider,
        software_delivery_tools_enabled=software_delivery_tools_enabled(settings),
    )
