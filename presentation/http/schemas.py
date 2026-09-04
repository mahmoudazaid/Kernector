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
