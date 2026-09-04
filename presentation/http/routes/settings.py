"""Versioned runtime settings catalog route."""

from fastapi import APIRouter

from presentation.http.deps import RuntimeSettingsDep
from presentation.http.errors import problem_responses
from presentation.http.schemas import (
    ModelSettingDefResponse,
    OllamaSettingsResponse,
    OpenRouterSettingsResponse,
    RuntimeSettingsResponse,
)

router = APIRouter(prefix="/api/v1", tags=["settings"])


@router.get(
    "/settings",
    responses=problem_responses(405, 500),
)
def runtime_settings(use_case: RuntimeSettingsDep) -> RuntimeSettingsResponse:
    """Expose providers, env defaults, and model-settings catalog for Settings UI."""
    catalog = use_case.execute()
    return RuntimeSettingsResponse(
        providers=list(catalog.providers),
        default_provider=catalog.default_provider,
        openrouter=OpenRouterSettingsResponse(
            models=list(catalog.openrouter.models),
            default_model=catalog.openrouter.default_model,
        ),
        ollama=OllamaSettingsResponse(
            default_base_url=catalog.ollama.default_base_url,
            default_model=catalog.ollama.default_model,
        ),
        model_settings=[
            ModelSettingDefResponse(
                key=setting.key,
                label=setting.label,
                widget=setting.widget,
                default=float(setting.default),
                min_value=float(setting.min_value),
                max_value=float(setting.max_value),
                step=float(setting.step),
                help=setting.help,
                providers=list(setting.providers),
            )
            for setting in catalog.model_settings
        ],
    )
