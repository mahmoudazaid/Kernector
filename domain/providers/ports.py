"""Ports for workspace AI credential vault (#461)."""

from __future__ import annotations

from typing import Protocol

from domain.providers.credentials import WorkspaceCredential


class CredentialStore(Protocol):
    """Workspace-bound credential persistence (metadata + encrypted writes)."""

    def insert_active(
        self,
        *,
        credential_id: str,
        provider: str,
        plaintext_secret: str,
        key_hint: str,
        created_by: str,
    ) -> WorkspaceCredential:
        """Insert an active credential; encrypts *plaintext_secret* at rest."""
        ...

    def replace_active_secret(
        self, provider: str, plaintext_secret: str, *, key_hint: str
    ) -> WorkspaceCredential:
        """Overwrite the active secret without setting ``rotated_at``."""
        ...

    def rotate_active_secret(
        self, provider: str, plaintext_secret: str, *, key_hint: str
    ) -> WorkspaceCredential:
        """Overwrite the active secret and set ``rotated_at``."""
        ...

    def disable_active(self, provider: str) -> WorkspaceCredential:
        """Transition the active credential to disabled."""
        ...

    def revoke_active(self, provider: str) -> WorkspaceCredential:
        """Transition the active credential to revoked."""
        ...

    def get_active(self, provider: str) -> WorkspaceCredential | None:
        """Return metadata for the active credential for *provider*, if any."""
        ...

    def get(self, credential_id: str) -> WorkspaceCredential | None:
        """Return metadata for *credential_id* in this workspace, if any."""
        ...

    def list(self) -> tuple[WorkspaceCredential, ...]:
        """Return all credential metadata rows for this workspace."""
        ...


class CredentialSecretReveal(Protocol):
    """Narrow decrypt boundary for provider-call materialization (#462/#463)."""

    def reveal_active_secret(self, provider: str) -> str:
        """Return plaintext for the active credential, or raise if unavailable."""
        ...
