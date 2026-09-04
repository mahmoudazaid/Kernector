"""Runtime settings catalog for presentation adapters (Next.js / HTTP).

Assembles provider lists, env defaults, and the domain model-settings
allowlist into a UI-agnostic view. No I/O — composition injects defaults;
Ollama reachability lives in :class:`ProbeOllamaStatus`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from application.errors import ApplicationValidationError
from domain.model_settings import SETTINGS


@dataclass(frozen=True, slots=True)
class RuntimeSettingsDefaults:
    """Env/config snapshot used to seed the settings catalog."""

    provider: str
    openrouter_models: tuple[str, ...]
    openrouter_default_model: str | None
    ollama_default_base_url: str | None
    ollama_default_model: str | None


@dataclass(frozen=True, slots=True)
class OpenRouterSettingsView:
    """OpenRouter model list and default from runtime config."""

    models: tuple[str, ...]
    default_model: str | None


@dataclass(frozen=True, slots=True)
class OllamaSettingsView:
    """Ollama default URL and model from runtime config."""

    default_base_url: str | None
    default_model: str | None


@dataclass(frozen=True, slots=True)
class ModelSettingDef:
    """One generation setting exposed to UI (mirrors domain ``Setting``)."""

    key: str
    label: str
    widget: str
    default: float | int
    min_value: float | int
    max_value: float | int
    step: float | int
    help: str
    providers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuntimeSettingsCatalog:
    """Read-only catalog for provider/model/settings controls."""

    providers: tuple[str, ...]
    default_provider: str
    openrouter: OpenRouterSettingsView
    ollama: OllamaSettingsView
    model_settings: tuple[ModelSettingDef, ...]


@dataclass(frozen=True, slots=True)
class OllamaStatus:
    """Reachability and installed models for an Ollama base URL."""

    reachable: bool
    models: tuple[str, ...]


class GetRuntimeSettings:
    """Build the runtime settings catalog from injected defaults + domain."""

    def __init__(
        self,
        providers: Sequence[str],
        defaults: RuntimeSettingsDefaults,
    ) -> None:
        self._providers = tuple(providers)
        self._defaults = defaults

    def execute(self) -> RuntimeSettingsCatalog:
        """Return the catalog used by settings HTTP / Next.js UI."""
        return RuntimeSettingsCatalog(
            providers=self._providers,
            default_provider=self._defaults.provider,
            openrouter=OpenRouterSettingsView(
                models=self._defaults.openrouter_models,
                default_model=self._defaults.openrouter_default_model,
            ),
            ollama=OllamaSettingsView(
                default_base_url=self._defaults.ollama_default_base_url,
                default_model=self._defaults.ollama_default_model,
            ),
            model_settings=tuple(
                ModelSettingDef(
                    key=setting.key,
                    label=setting.label,
                    widget=setting.widget,
                    default=_as_number(setting.default),
                    min_value=_as_number(setting.min_value),
                    max_value=_as_number(setting.max_value),
                    step=_as_number(setting.step),
                    help=setting.help,
                    providers=setting.providers,
                )
                for setting in SETTINGS
            ),
        )


class ProbeOllamaStatus:
    """Probe Ollama reachability through an injected callable (no I/O here)."""

    def __init__(
        self,
        probe: Callable[[str], Mapping[str, object]],
    ) -> None:
        self._probe = probe

    def execute(self, base_url: str) -> OllamaStatus:
        """Return status for ``base_url``.

        Args:
            base_url: Ollama server URL (non-blank).

        Returns:
            OllamaStatus: Reachability flag and installed model names.

        Raises:
            ApplicationValidationError: If ``base_url`` is blank.
        """
        if not isinstance(base_url, str) or not base_url.strip():
            raise ApplicationValidationError("base_url must be non-empty")
        raw = self._probe(base_url.strip())
        models = raw.get("models", ())
        if not isinstance(models, Sequence) or isinstance(models, (str, bytes)):
            models = ()
        return OllamaStatus(
            reachable=bool(raw.get("reachable")),
            models=tuple(str(m) for m in models),
        )


def _as_number(value: object) -> float | int:
    """Coerce domain setting numerics for the catalog view."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApplicationValidationError(
            f"model setting numeric must be int or float, got {value!r}"
        )
    return value
