"""AES-256-GCM secret encryption for the workspace credential vault (#461)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12
_KEY_BYTES = 32
_AAD_SCHEMA = "kernector.credential.v1"


class SecretCryptoError(RuntimeError):
    """Authenticated encryption failed or configuration is invalid."""


@dataclass(frozen=True, slots=True)
class SecretAad:
    """Canonical associated data bound into AES-GCM authentication."""

    credential_id: str
    workspace_id: str
    provider: str
    schema_version: int
    encryption_key_version: int

    def encode(self) -> bytes:
        """Return a stable AAD encoding for encrypt/decrypt."""
        parts = (
            _AAD_SCHEMA,
            str(self.schema_version),
            self.credential_id,
            self.workspace_id,
            self.provider,
            str(self.encryption_key_version),
        )
        return b"\x1f".join(part.encode("utf-8") for part in parts)


@dataclass(frozen=True, slots=True)
class SecretEnvelope:
    """Ciphertext plus nonce and key version metadata."""

    ciphertext: bytes
    nonce: bytes
    key_version: int


def secret_crypto_from_vault_settings(master_key: bytes | None, key_version: int | None) -> SecretCrypto:
    """Build ``SecretCrypto`` or fail closed when vault settings are incomplete."""
    if master_key is None or key_version is None:
        raise SecretCryptoError("credential vault master key is required")
    return SecretCrypto(master_key=master_key, key_version=key_version)


class SecretCrypto:
    """AES-256-GCM helper keyed by a deployment master key."""

    def __init__(self, *, master_key: bytes, key_version: int) -> None:
        if not isinstance(master_key, (bytes, bytearray)) or len(master_key) != _KEY_BYTES:
            raise SecretCryptoError("master key must be exactly 32 bytes")
        if not isinstance(key_version, int) or key_version < 1:
            raise SecretCryptoError("key version must be a positive integer")
        self._master_key = bytes(master_key)
        self._key_version = key_version
        self._aesgcm = AESGCM(self._master_key)

    @property
    def key_version(self) -> int:
        return self._key_version

    def encrypt(self, plaintext: bytes, *, aad: SecretAad) -> SecretEnvelope:
        if aad.encryption_key_version != self._key_version:
            raise SecretCryptoError("AAD encryption key version mismatch")
        nonce = os.urandom(_NONCE_BYTES)
        try:
            ciphertext = self._aesgcm.encrypt(nonce, plaintext, aad.encode())
        except Exception as error:
            raise SecretCryptoError("encryption failed") from error
        return SecretEnvelope(
            ciphertext=ciphertext,
            nonce=nonce,
            key_version=self._key_version,
        )

    def decrypt(self, envelope: SecretEnvelope, *, aad: SecretAad) -> bytes:
        if envelope.key_version != self._key_version:
            raise SecretCryptoError("envelope key version mismatch")
        if aad.encryption_key_version != self._key_version:
            raise SecretCryptoError("AAD encryption key version mismatch")
        if len(envelope.nonce) != _NONCE_BYTES:
            raise SecretCryptoError("invalid nonce")
        try:
            return self._aesgcm.decrypt(
                envelope.nonce, envelope.ciphertext, aad.encode()
            )
        except InvalidTag as error:
            raise SecretCryptoError("decryption failed") from error
        except Exception as error:
            raise SecretCryptoError("decryption failed") from error

    def __repr__(self) -> str:
        return (
            f"SecretCrypto(key_version={self._key_version}, master_key='REDACTED')"
        )
