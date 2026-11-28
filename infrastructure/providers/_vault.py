"""Private shared helpers for credential vault SQLite adapters (#461)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from domain.providers.credentials import CredentialStatus, WorkspaceCredential
from infrastructure.catalog import _connection
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_schema import apply_migrations
from infrastructure.providers.secret_crypto import SecretAad, SecretCrypto, SecretEnvelope

# AAD schema version for credential envelopes (independent of catalog migration #).
CREDENTIAL_AAD_SCHEMA_VERSION = 1


class CredentialVaultStoreError(RuntimeError):
    """SQLite access to workspace AI credential tables failed."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def require_crypto(crypto: SecretCrypto | None) -> SecretCrypto:
    if crypto is None:
        raise CredentialVaultStoreError("credential vault master key is required")
    return crypto


def ensure_migrations(path: Path) -> None:
    try:
        apply_migrations(path)
    except CatalogError as error:
        raise CredentialVaultStoreError(
            f"could not apply credential vault migrations at {path}"
        ) from error


def metadata_from_row(row: sqlite3.Row) -> WorkspaceCredential:
    return WorkspaceCredential(
        credential_id=row["id"],
        workspace_id=row["workspace_id"],
        provider=row["provider"],
        key_hint=row["key_hint"],
        status=CredentialStatus(row["status"]),
        encryption_key_version=int(row["encryption_key_version"]),
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        rotated_at=row["rotated_at"],
    )


def build_aad(
    *,
    credential_id: str,
    workspace_id: str,
    provider: str,
    encryption_key_version: int,
) -> SecretAad:
    return SecretAad(
        credential_id=credential_id,
        workspace_id=workspace_id,
        provider=provider,
        schema_version=CREDENTIAL_AAD_SCHEMA_VERSION,
        encryption_key_version=encryption_key_version,
    )


def encrypt_secret(
    crypto: SecretCrypto,
    plaintext_secret: str,
    *,
    credential_id: str,
    workspace_id: str,
    provider: str,
) -> SecretEnvelope:
    aad = build_aad(
        credential_id=credential_id,
        workspace_id=workspace_id,
        provider=provider,
        encryption_key_version=crypto.key_version,
    )
    return crypto.encrypt(plaintext_secret.encode("utf-8"), aad=aad)


def decrypt_secret(
    crypto: SecretCrypto,
    *,
    ciphertext: bytes,
    nonce: bytes,
    key_version: int,
    credential_id: str,
    workspace_id: str,
    provider: str,
) -> str:
    aad = build_aad(
        credential_id=credential_id,
        workspace_id=workspace_id,
        provider=provider,
        encryption_key_version=key_version,
    )
    envelope = SecretEnvelope(
        ciphertext=ciphertext,
        nonce=nonce,
        key_version=key_version,
    )
    return crypto.decrypt(envelope, aad=aad).decode("utf-8")


@contextmanager
def vault_connection(path: Path, *, write: bool) -> Iterator[sqlite3.Connection]:
    try:
        connection = _connection.connect(path)
    except sqlite3.Error as error:
        raise CredentialVaultStoreError(
            f"could not open credential vault at {path}"
        ) from error
    connection.row_factory = sqlite3.Row
    begin = "BEGIN IMMEDIATE" if write else "BEGIN"
    try:
        connection.execute(begin)
    except sqlite3.Error as error:
        connection.close()
        raise CredentialVaultStoreError(
            "could not begin credential vault transaction"
        ) from error
    try:
        yield connection
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    else:
        connection.execute("COMMIT")
    finally:
        connection.close()
