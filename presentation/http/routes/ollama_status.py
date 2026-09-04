"""Versioned Ollama status probe route."""

from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Query
from pydantic import AfterValidator

from presentation.http.deps import ProbeOllamaStatusDep
from presentation.http.errors import problem_responses
from presentation.http.schemas import OllamaStatusResponse

router = APIRouter(prefix="/api/v1", tags=["settings"])

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _require_local_base_url(value: str) -> str:
    """Accept only non-blank local Ollama URLs (no SSRF via arbitrary hosts)."""
    stripped = value.strip()
    if not stripped:
        raise ValueError("base_url must be non-empty")
    parsed = urlparse(stripped)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in _LOCAL_HOSTS:
        raise ValueError("base_url must be a local Ollama address")
    return stripped


BaseUrlQuery = Annotated[
    str,
    Query(..., min_length=1, description="Local Ollama server base URL"),
    AfterValidator(_require_local_base_url),
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
