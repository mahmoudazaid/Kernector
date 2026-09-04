"""Versioned capabilities prove-out route."""

from fastapi import APIRouter

from composition import available_providers, software_delivery_tools_enabled
from presentation.http.deps import SettingsDep
from presentation.http.errors import problem_responses
from presentation.http.schemas import CapabilitiesResponse

router = APIRouter(prefix="/api/v1", tags=["capabilities"])


@router.get(
    "/capabilities",
    responses=problem_responses(405, 500),
)
def capabilities(settings: SettingsDep) -> CapabilitiesResponse:
    """Expose buildable providers and tool-pack enablement via composition."""
    return CapabilitiesResponse(
        providers=list(available_providers()),
        default_provider=settings.provider,
        software_delivery_tools_enabled=software_delivery_tools_enabled(settings),
    )
