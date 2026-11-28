"""Provider capability registry — single source of advertised fitness (#462)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from domain.errors import UnknownProviderError

ProviderId = Literal["openrouter", "openai", "anthropic", "gemini", "ollama"]
Purpose = Literal["chat", "rewrite", "embedding", "judge"]

_KNOWN: tuple[ProviderId, ...] = (
    "openrouter",
    "openai",
    "anthropic",
    "gemini",
    "ollama",
)

_CHAT_PURPOSES: frozenset[Purpose] = frozenset({"chat", "rewrite", "judge"})
_PARAMETERS = frozenset({"temperature", "max_tokens", "top_p"})


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Advertised technical capabilities for one provider."""

    chat: bool
    embeddings: bool
    custom_base_url: bool
    model_discovery: bool
    parameters: frozenset[str]


_CAPABILITIES: dict[ProviderId, ProviderCapabilities] = {
    "openrouter": ProviderCapabilities(
        chat=True,
        embeddings=True,
        custom_base_url=True,
        model_discovery=False,
        parameters=_PARAMETERS,
    ),
    "openai": ProviderCapabilities(
        chat=True,
        embeddings=True,
        custom_base_url=False,
        model_discovery=False,
        parameters=_PARAMETERS,
    ),
    "anthropic": ProviderCapabilities(
        chat=True,
        embeddings=False,
        custom_base_url=False,
        model_discovery=False,
        parameters=_PARAMETERS,
    ),
    "gemini": ProviderCapabilities(
        chat=True,
        embeddings=True,
        custom_base_url=False,
        model_discovery=False,
        parameters=_PARAMETERS,
    ),
    "ollama": ProviderCapabilities(
        chat=True,
        embeddings=False,
        custom_base_url=True,
        model_discovery=True,
        parameters=_PARAMETERS,
    ),
}


def known_providers() -> tuple[ProviderId, ...]:
    """Return every registered provider id in stable order."""
    return _KNOWN


def capabilities_for(provider: str) -> ProviderCapabilities:
    """Return advertised capabilities for ``provider``.

    Raises:
        UnknownProviderError: ``provider`` is not in the registry.
    """
    return _require_known(provider)


def supports(provider: str, purpose: Purpose) -> bool:
    """Return whether ``provider`` advertises fitness for ``purpose``.

    Raises:
        UnknownProviderError: ``provider`` is not in the registry.
    """
    caps = _require_known(provider)
    if purpose in _CHAT_PURPOSES:
        return caps.chat
    return caps.embeddings


def _require_known(provider: str) -> ProviderCapabilities:
    if provider not in _CAPABILITIES:
        raise UnknownProviderError("Unknown provider.")
    return _CAPABILITIES[provider]  # type: ignore[index]
