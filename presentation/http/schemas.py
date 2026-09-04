"""OpenAPI / wire schemas for the HTTP presentation adapter."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Operational readiness payload for unversioned ``GET /health``."""

    status: str = Field(examples=["ok"])


class CapabilitiesResponse(BaseModel):
    """Minimal read-only prove-out for the composition boundary."""

    providers: list[str]
    default_provider: str
    software_delivery_tools_enabled: bool


class OpenRouterSettingsResponse(BaseModel):
    """OpenRouter models and default from runtime config."""

    models: list[str]
    default_model: str | None = None


class OllamaSettingsResponse(BaseModel):
    """Ollama defaults from runtime config (live models come from probe)."""

    default_base_url: str | None = None
    default_model: str | None = None


class ModelSettingDefResponse(BaseModel):
    """One generation setting for Settings UI controls."""

    key: str
    label: str
    widget: str
    default: float
    min_value: float
    max_value: float
    step: float
    help: str
    providers: list[str]


class RuntimeSettingsResponse(BaseModel):
    """Catalog for provider/model/settings controls (Streamlit sidebar parity)."""

    providers: list[str]
    default_provider: str
    openrouter: OpenRouterSettingsResponse
    ollama: OllamaSettingsResponse
    model_settings: list[ModelSettingDefResponse]


class OllamaStatusResponse(BaseModel):
    """Ollama reachability and installed models for a base URL."""

    reachable: bool
    models: list[str]
