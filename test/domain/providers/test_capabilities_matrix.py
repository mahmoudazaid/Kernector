"""Capability registry matrix — independent literals (#462)."""

from __future__ import annotations

import pytest

from domain.errors import UnknownProviderError
from domain.providers import (
    ProviderCapabilities,
    capabilities_for,
    known_providers,
    supports,
)

# Independent source of truth for advertised capabilities (not imported from
# the registry implementation table).
_EXPECTED_MATRIX: dict[str, ProviderCapabilities] = {
    "openrouter": ProviderCapabilities(
        chat=True,
        embeddings=True,
        custom_base_url=True,
        model_discovery=False,
        parameters=frozenset({"temperature", "max_tokens", "top_p"}),
    ),
    "openai": ProviderCapabilities(
        chat=True,
        embeddings=True,
        custom_base_url=False,
        model_discovery=False,
        parameters=frozenset({"temperature", "max_tokens", "top_p"}),
    ),
    "anthropic": ProviderCapabilities(
        chat=True,
        embeddings=False,
        custom_base_url=False,
        model_discovery=False,
        parameters=frozenset({"temperature", "max_tokens", "top_p"}),
    ),
    "gemini": ProviderCapabilities(
        chat=True,
        embeddings=True,
        custom_base_url=False,
        model_discovery=False,
        parameters=frozenset({"temperature", "max_tokens", "top_p"}),
    ),
    "ollama": ProviderCapabilities(
        chat=True,
        embeddings=False,
        custom_base_url=True,
        model_discovery=True,
        parameters=frozenset({"temperature", "max_tokens", "top_p"}),
    ),
}

_CHAT_PURPOSES = ("chat", "rewrite", "judge")
_ALL_PURPOSES = ("chat", "rewrite", "embedding", "judge")


def test_known_providers_lists_the_five_native_ids() -> None:
    assert known_providers() == (
        "openrouter",
        "openai",
        "anthropic",
        "gemini",
        "ollama",
    )


@pytest.mark.parametrize("provider", list(_EXPECTED_MATRIX))
def test_capabilities_for_matches_literal_matrix(provider: str) -> None:
    assert capabilities_for(provider) == _EXPECTED_MATRIX[provider]


@pytest.mark.parametrize("provider", list(_EXPECTED_MATRIX))
@pytest.mark.parametrize("purpose", _CHAT_PURPOSES)
def test_chat_capable_providers_support_chat_rewrite_judge(
    provider: str, purpose: str
) -> None:
    caps = _EXPECTED_MATRIX[provider]
    assert supports(provider, purpose) is caps.chat


@pytest.mark.parametrize("provider", list(_EXPECTED_MATRIX))
def test_embedding_purpose_follows_embeddings_flag(provider: str) -> None:
    caps = _EXPECTED_MATRIX[provider]
    assert supports(provider, "embedding") is caps.embeddings


def test_anthropic_is_not_embedding_capable() -> None:
    assert capabilities_for("anthropic").embeddings is False
    assert supports("anthropic", "embedding") is False


def test_unknown_provider_raises_on_capabilities_for() -> None:
    with pytest.raises(UnknownProviderError, match="Unknown provider"):
        capabilities_for("unknown-vendor")


def test_unknown_provider_raises_on_supports() -> None:
    with pytest.raises(UnknownProviderError, match="Unknown provider"):
        supports("unknown-vendor", "chat")


@pytest.mark.parametrize("purpose", _ALL_PURPOSES)
def test_unknown_provider_raises_for_every_purpose(purpose: str) -> None:
    with pytest.raises(UnknownProviderError):
        supports("not-a-provider", purpose)
