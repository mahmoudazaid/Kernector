"""SQLite CredentialSecretReveal adapter (#461).

Distinct from ``SqlCredentialStore``; shares only private vault helpers.
Not wired into LLM composition factories in this story (#462/#463).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from domain.providers.credentials import CredentialStatus
from domain.providers.errors import CredentialNotFoundError
from infrastructure.catalog.workspace import require_workspace_id
from infrastructure.providers._vault import (
    CredentialVaultStoreError,
    decrypt_secret,
    ensure_migrations,
    require_crypto,
    vault_connection,
)
from infrastructure.providers.secret_crypto import SecretCrypto, SecretCryptoError


class SqlCredentialSecretReveal:
    """Decrypt active workspace credentials for the provider-call boundary."""

    def __init__(
        self,
        path: Path,
        workspace_id: str,
        *,
        crypto: SecretCrypto | None = None,
    ) -> None:
        self._workspace_id = require_workspace_id(workspace_id)
        self._path = path
        self._crypto = require_crypto(crypto)
        ensure_migrations(path)

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    def reveal_active_secret(self, provider: str) -> str:
        with vault_connection(self._path, write=False) as connection:
            try:
                row = connection.execute(
                    "SELECT id, provider, encrypted_secret, nonce, "
                    "encryption_key_version FROM workspace_ai_credentials "
                    "WHERE workspace_id = ? AND provider = ? AND status = ?",
                    (
                        self._workspace_id,
                        provider,
                        CredentialStatus.ACTIVE.value,
                    ),
                ).fetchone()
            except sqlite3.Error as error:
                raise CredentialVaultStoreError(
                    "could not read credential secret"
                ) from error
        if row is None:
            raise CredentialNotFoundError("active credential not found")
        try:
            return decrypt_secret(
                self._crypto,
                ciphertext=bytes(row["encrypted_secret"]),
                nonce=bytes(row["nonce"]),
                key_version=int(row["encryption_key_version"]),
                credential_id=row["id"],
                workspace_id=self._workspace_id,
                provider=row["provider"],
            )
        except SecretCryptoError as error:
            raise CredentialVaultStoreError(
                "could not decrypt credential secret"
            ) from error
