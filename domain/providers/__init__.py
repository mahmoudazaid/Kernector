"""Workspace AI provider capability registry and credential vault models."""

from domain.providers.capabilities import (
    ProviderCapabilities,
    ProviderId,
    Purpose,
    capabilities_for,
    known_providers,
    supports,
)
from domain.providers.credentials import (
    CredentialStatus,
    WorkspaceCredential,
    key_hint_for_secret,
    new_credential_id,
)
from domain.providers.gating import require_provider_purpose
from domain.providers.ports import CredentialSecretReveal, CredentialStore

__all__ = [
    "CredentialSecretReveal",
    "CredentialStatus",
    "CredentialStore",
    "ProviderCapabilities",
    "ProviderId",
    "Purpose",
    "WorkspaceCredential",
    "capabilities_for",
    "key_hint_for_secret",
    "known_providers",
    "new_credential_id",
    "require_provider_purpose",
    "supports",
]
