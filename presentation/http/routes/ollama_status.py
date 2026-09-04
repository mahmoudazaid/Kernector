"""Versioned Ollama status probe route."""

from fastapi import APIRouter, HTTPException

from presentation.http.deps import ProbeOllamaStatusDep, SettingsDep
from presentation.http.errors import problem_responses
from presentation.http.schemas import OllamaStatusResponse

router = APIRouter(prefix="/api/v1", tags=["settings"])


@router.get(
    "/ollama/status",
    responses=problem_responses(405, 409, 500),
)
def ollama_status(
    use_case: ProbeOllamaStatusDep,
    settings: SettingsDep,
) -> OllamaStatusResponse:
    """Probe the configured Ollama base URL (never a client-supplied target)."""
    configured = (settings.ollama.base_url or "").strip()
    if not configured:
        raise HTTPException(
            status_code=409,
            detail="OLLAMA_BASE_URL is not configured",
        )
    status = use_case.execute(configured)
    return OllamaStatusResponse(
        reachable=status.reachable,
        models=list(status.models),
    )
