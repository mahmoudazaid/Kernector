"""SQLite CredentialStore adapter for workspace AI credentials (#461)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from domain.providers.credentials import CredentialStatus, WorkspaceCredential
from domain.providers.errors import CredentialConflictError, CredentialNotFoundError
from infrastructure.catalog.workspace import require_workspace_id
from infrastructure.providers._vault import (
    CredentialVaultStoreError,
    encrypt_secret,
    ensure_migrations,
    metadata_from_row,
    now_iso,
    require_crypto,
    vault_connection,
)
from infrastructure.providers.secret_crypto import SecretCrypto


class SqlCredentialStore:
    """Workspace-bound credential persistence (metadata + encrypted writes)."""

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

    def insert_active(
        self,
        *,
        credential_id: str,
        provider: str,
        plaintext_secret: str,
        key_hint: str,
        created_by: str,
    ) -> WorkspaceCredential:
        envelope = encrypt_secret(
            self._crypto,
            plaintext_secret,
            credential_id=credential_id,
            workspace_id=self._workspace_id,
            provider=provider,
        )
        now = now_iso()
        with vault_connection(self._path, write=True) as connection:
            try:
                connection.execute(
                    "INSERT INTO workspace_ai_credentials ("
                    "id, workspace_id, provider, encrypted_secret, nonce, "
                    "encryption_key_version, key_hint, status, created_by, "
                    "created_at, updated_at, rotated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                    (
                        credential_id,
                        self._workspace_id,
                        provider,
                        envelope.ciphertext,
                        envelope.nonce,
                        envelope.key_version,
                        key_hint,
                        CredentialStatus.ACTIVE.value,
                        created_by,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise CredentialConflictError(
                    "active credential already exists for provider"
                ) from error
            except sqlite3.Error as error:
                raise CredentialVaultStoreError(
                    "could not insert credential"
                ) from error
        metadata = self.get(credential_id)
        if metadata is None:
            raise CredentialVaultStoreError("credential insert did not persist")
        return metadata

    def replace_active_secret(
        self, provider: str, plaintext_secret: str, *, key_hint: str
    ) -> WorkspaceCredential:
        return self._rewrite_active_secret(
            provider, plaintext_secret, key_hint=key_hint, mark_rotated=False
        )

    def rotate_active_secret(
        self, provider: str, plaintext_secret: str, *, key_hint: str
    ) -> WorkspaceCredential:
        return self._rewrite_active_secret(
            provider, plaintext_secret, key_hint=key_hint, mark_rotated=True
        )

    def disable_active(self, provider: str) -> WorkspaceCredential:
        return self._set_active_status(provider, CredentialStatus.DISABLED)

    def revoke_active(self, provider: str) -> WorkspaceCredential:
        return self._set_active_status(provider, CredentialStatus.REVOKED)

    def get_active(self, provider: str) -> WorkspaceCredential | None:
        with vault_connection(self._path, write=False) as connection:
            row = connection.execute(
                "SELECT * FROM workspace_ai_credentials "
                "WHERE workspace_id = ? AND provider = ? AND status = ?",
                (self._workspace_id, provider, CredentialStatus.ACTIVE.value),
            ).fetchone()
        return None if row is None else metadata_from_row(row)

    def get(self, credential_id: str) -> WorkspaceCredential | None:
        with vault_connection(self._path, write=False) as connection:
            row = connection.execute(
                "SELECT * FROM workspace_ai_credentials "
                "WHERE workspace_id = ? AND id = ?",
                (self._workspace_id, credential_id),
            ).fetchone()
        return None if row is None else metadata_from_row(row)

    def list(self) -> tuple[WorkspaceCredential, ...]:
        with vault_connection(self._path, write=False) as connection:
            rows = connection.execute(
                "SELECT * FROM workspace_ai_credentials "
                "WHERE workspace_id = ? ORDER BY created_at, id",
                (self._workspace_id,),
            ).fetchall()
        return tuple(metadata_from_row(row) for row in rows)

    def _rewrite_active_secret(
        self,
        provider: str,
        plaintext_secret: str,
        *,
        key_hint: str,
        mark_rotated: bool,
    ) -> WorkspaceCredential:
        active = self.get_active(provider)
        if active is None:
            raise CredentialNotFoundError("active credential not found")
        envelope = encrypt_secret(
            self._crypto,
            plaintext_secret,
            credential_id=active.credential_id,
            workspace_id=self._workspace_id,
            provider=provider,
        )
        now = now_iso()
        rotated_at = now if mark_rotated else active.rotated_at
        with vault_connection(self._path, write=True) as connection:
            try:
                cursor = connection.execute(
                    "UPDATE workspace_ai_credentials SET "
                    "encrypted_secret = ?, nonce = ?, encryption_key_version = ?, "
                    "key_hint = ?, updated_at = ?, rotated_at = ? "
                    "WHERE workspace_id = ? AND provider = ? AND status = ? "
                    "AND id = ?",
                    (
                        envelope.ciphertext,
                        envelope.nonce,
                        envelope.key_version,
                        key_hint,
                        now,
                        rotated_at,
                        self._workspace_id,
                        provider,
                        CredentialStatus.ACTIVE.value,
                        active.credential_id,
                    ),
                )
            except sqlite3.Error as error:
                raise CredentialVaultStoreError(
                    "could not update credential secret"
                ) from error
            if cursor.rowcount != 1:
                raise CredentialNotFoundError("active credential not found")
        metadata = self.get(active.credential_id)
        if metadata is None:
            raise CredentialVaultStoreError("credential update did not persist")
        return metadata

    def _set_active_status(
        self, provider: str, status: CredentialStatus
    ) -> WorkspaceCredential:
        now = now_iso()
        with vault_connection(self._path, write=True) as connection:
            try:
                cursor = connection.execute(
                    "UPDATE workspace_ai_credentials SET status = ?, updated_at = ? "
                    "WHERE workspace_id = ? AND provider = ? AND status = ?",
                    (
                        status.value,
                        now,
                        self._workspace_id,
                        provider,
                        CredentialStatus.ACTIVE.value,
                    ),
                )
            except sqlite3.Error as error:
                raise CredentialVaultStoreError(
                    "could not update credential status"
                ) from error
            if cursor.rowcount != 1:
                raise CredentialNotFoundError("active credential not found")
            row = connection.execute(
                "SELECT * FROM workspace_ai_credentials "
                "WHERE workspace_id = ? AND provider = ? AND status = ? "
                "ORDER BY updated_at DESC, id DESC LIMIT 1",
                (self._workspace_id, provider, status.value),
            ).fetchone()
        if row is None:
            raise CredentialVaultStoreError("credential status update did not persist")
        return metadata_from_row(row)
