"""Workspace AI provider capability registry (#462)."""

from domain.providers.capabilities import (
    ProviderCapabilities,
    ProviderId,
    Purpose,
    capabilities_for,
    known_providers,
    supports,
)
from domain.providers.gating import require_provider_purpose

__all__ = [
    "ProviderCapabilities",
    "ProviderId",
    "Purpose",
    "capabilities_for",
    "known_providers",
    "require_provider_purpose",
    "supports",
]
