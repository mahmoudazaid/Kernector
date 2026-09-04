"""Versioned Ollama status probe route."""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AfterValidator

from presentation.http.deps import ProbeOllamaStatusDep
from presentation.http.errors import problem_responses
from presentation.http.schemas import OllamaStatusResponse

router = APIRouter(prefix="/api/v1", tags=["settings"])


def _require_non_blank_base_url(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("base_url must be non-empty")
    return stripped


BaseUrlQuery = Annotated[
    str,
    Query(..., min_length=1, description="Ollama server base URL"),
    AfterValidator(_require_non_blank_base_url),
]


@router.get(
    "/ollama/status",
    responses=problem_responses(405, 422, 500),
)
def ollama_status(
    use_case: ProbeOllamaStatusDep,
    base_url: BaseUrlQuery,
) -> OllamaStatusResponse:
    """Probe Ollama reachability and list installed models for ``base_url``."""
    status = use_case.execute(base_url)
    return OllamaStatusResponse(
        reachable=status.reachable,
        models=list(status.models),
    )
