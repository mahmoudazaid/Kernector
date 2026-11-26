"""Validate and project user preferences against the runtime catalog (#182)."""

from __future__ import annotations

from dataclasses import dataclass

from application.errors import ApplicationValidationError
from application.runtime_settings import RuntimeSettingsCatalog


@dataclass(frozen=True, slots=True)
class PreferenceView:
    """Preferences as returned to clients."""

    provider: str | None
    model: str | None
    usable: bool


def catalog_allows_pair(
    catalog: RuntimeSettingsCatalog, provider: str, model: str
) -> bool:
    """Return whether *provider*/*model* is offered by *catalog*."""
    if provider not in catalog.providers:
        return False
    if not model.strip():
        return False
    if provider == "openrouter":
        models = catalog.openrouter.models
        if model in models:
            return True
        default = catalog.openrouter.default_model
        return default is not None and model == default and not models
    if provider == "ollama":
        default = catalog.ollama.default_model
        if default is not None and model == default:
            return True
        # Ollama installed models are probed live; allow non-empty when provider
        # is enabled and catalog advertises ollama.
        return True
    return False


def require_catalog_pair(
    catalog: RuntimeSettingsCatalog, provider: str, model: str
) -> None:
    """Raise when *provider*/*model* is not offered by *catalog*."""
    if not catalog_allows_pair(catalog, provider, model):
        raise ApplicationValidationError(
            "provider/model pair is not available in the runtime catalog"
        )


def project_preferences(
    catalog: RuntimeSettingsCatalog,
    *,
    provider: str | None,
    model: str | None,
) -> PreferenceView:
    """Project stored prefs; missing or stale pairs are not usable."""
    if provider is None or model is None:
        return PreferenceView(provider=provider, model=model, usable=False)
    usable = catalog_allows_pair(catalog, provider, model)
    return PreferenceView(provider=provider, model=model, usable=usable)
