"""Create, replace, rotate, disable, and revoke workspace AI credentials (#461)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from domain.providers.capabilities import capabilities_for
from domain.providers.credentials import (
    WorkspaceCredential,
    key_hint_for_secret,
    new_credential_id,
)
from domain.providers.ports import CredentialStore

__all__ = [
    "CreateWorkspaceCredential",
    "CreateWorkspaceCredentialRequest",
    "DisableWorkspaceCredential",
    "GetActiveWorkspaceCredential",
    "ListWorkspaceCredentials",
    "ReplaceWorkspaceCredential",
    "RevokeWorkspaceCredential",
    "RotateWorkspaceCredential",
    "key_hint_for_secret",
]


@dataclass(frozen=True, slots=True)
class CreateWorkspaceCredentialRequest:
    provider: str
    plaintext_secret: str
    created_by: str


class CreateWorkspaceCredential:
    """Insert the first active credential for a provider in the workspace."""

    def __init__(
        self,
        *,
        store: CredentialStore,
        new_id: Callable[[], str] = new_credential_id,
    ) -> None:
        self._store = store
        self._new_id = new_id

    def execute(
        self, request: CreateWorkspaceCredentialRequest
    ) -> WorkspaceCredential:
        provider = _require_provider(request.provider)
        secret = _require_secret(request.plaintext_secret)
        created_by = request.created_by.strip() if isinstance(request.created_by, str) else ""
        if not created_by:
            raise ValueError("created_by must be non-blank")
        return self._store.insert_active(
            credential_id=self._new_id(),
            provider=provider,
            plaintext_secret=secret,
            key_hint=key_hint_for_secret(secret),
            created_by=created_by,
        )


class ReplaceWorkspaceCredential:
    """Overwrite the active secret without recording a rotation timestamp."""

    def __init__(self, *, store: CredentialStore) -> None:
        self._store = store

    def execute(self, *, provider: str, plaintext_secret: str) -> WorkspaceCredential:
        known = _require_provider(provider)
        secret = _require_secret(plaintext_secret)
        return self._store.replace_active_secret(
            known, secret, key_hint=key_hint_for_secret(secret)
        )


class RotateWorkspaceCredential:
    """Overwrite the active secret and set ``rotated_at``."""

    def __init__(self, *, store: CredentialStore) -> None:
        self._store = store

    def execute(self, *, provider: str, plaintext_secret: str) -> WorkspaceCredential:
        known = _require_provider(provider)
        secret = _require_secret(plaintext_secret)
        return self._store.rotate_active_secret(
            known, secret, key_hint=key_hint_for_secret(secret)
        )


class DisableWorkspaceCredential:
    """Transition the active credential to disabled (terminal for #461)."""

    def __init__(self, *, store: CredentialStore) -> None:
        self._store = store

    def execute(self, provider: str) -> WorkspaceCredential:
        return self._store.disable_active(_require_provider(provider))


class RevokeWorkspaceCredential:
    """Transition the active credential to revoked (terminal)."""

    def __init__(self, *, store: CredentialStore) -> None:
        self._store = store

    def execute(self, provider: str) -> WorkspaceCredential:
        return self._store.revoke_active(_require_provider(provider))


class GetActiveWorkspaceCredential:
    def __init__(self, *, store: CredentialStore) -> None:
        self._store = store

    def execute(self, provider: str) -> WorkspaceCredential | None:
        return self._store.get_active(_require_provider(provider))


class ListWorkspaceCredentials:
    def __init__(self, *, store: CredentialStore) -> None:
        self._store = store

    def execute(self) -> tuple[WorkspaceCredential, ...]:
        return self._store.list()


def _require_provider(provider: str) -> str:
    raw = provider.strip() if isinstance(provider, str) else ""
    if not raw:
        raise ValueError("provider must be non-blank")
    capabilities_for(raw)
    return raw


def _require_secret(plaintext_secret: str) -> str:
    if not isinstance(plaintext_secret, str) or not plaintext_secret.strip():
        raise ValueError("plaintext_secret must be non-blank")
    return plaintext_secret
