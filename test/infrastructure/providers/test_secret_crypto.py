"""SecretCrypto AES-256-GCM contract (#461)."""

from __future__ import annotations

import base64

import pytest

from infrastructure.providers.secret_crypto import (
    SecretAad,
    SecretCrypto,
    SecretCryptoError,
    SecretEnvelope,
)


def _key32(seed: bytes = b"\x01" * 32) -> bytes:
    return seed


def _crypto(key: bytes | None = None, *, version: int = 1) -> SecretCrypto:
    return SecretCrypto(master_key=key or _key32(), key_version=version)


def _aad(**overrides: object) -> SecretAad:
    base = {
        "credential_id": "cred_1",
        "workspace_id": "ws-a",
        "provider": "openrouter",
        "schema_version": 1,
        "encryption_key_version": 1,
    }
    base.update(overrides)
    return SecretAad(**base)  # type: ignore[arg-type]


def test_encrypt_decrypt_round_trip() -> None:
    crypto = _crypto()
    aad = _aad()
    envelope = crypto.encrypt(b"test-live-secret", aad=aad)
    assert len(envelope.nonce) == 12
    assert envelope.key_version == 1
    assert envelope.ciphertext != b"test-live-secret"
    assert crypto.decrypt(envelope, aad=aad) == b"test-live-secret"


def test_wrong_master_key_fails_closed() -> None:
    aad = _aad()
    envelope = _crypto(_key32(b"\x01" * 32)).encrypt(b"secret", aad=aad)
    with pytest.raises(SecretCryptoError):
        _crypto(_key32(b"\x02" * 32)).decrypt(envelope, aad=aad)


def test_wrong_key_version_in_aad_fails_closed() -> None:
    crypto = _crypto(version=1)
    envelope = crypto.encrypt(b"secret", aad=_aad(encryption_key_version=1))
    with pytest.raises(SecretCryptoError):
        crypto.decrypt(envelope, aad=_aad(encryption_key_version=2))


def test_ciphertext_tamper_fails_closed() -> None:
    crypto = _crypto()
    aad = _aad()
    envelope = crypto.encrypt(b"secret", aad=aad)
    tampered = SecretEnvelope(
        ciphertext=bytes([envelope.ciphertext[0] ^ 0xFF]) + envelope.ciphertext[1:],
        nonce=envelope.nonce,
        key_version=envelope.key_version,
    )
    with pytest.raises(SecretCryptoError):
        crypto.decrypt(tampered, aad=aad)


def test_aad_swap_credential_id_fails() -> None:
    crypto = _crypto()
    envelope = crypto.encrypt(b"secret", aad=_aad(credential_id="cred_1"))
    with pytest.raises(SecretCryptoError):
        crypto.decrypt(envelope, aad=_aad(credential_id="cred_2"))


def test_aad_swap_provider_fails() -> None:
    crypto = _crypto()
    envelope = crypto.encrypt(b"secret", aad=_aad(provider="openrouter"))
    with pytest.raises(SecretCryptoError):
        crypto.decrypt(envelope, aad=_aad(provider="openai"))


def test_aad_swap_workspace_fails() -> None:
    crypto = _crypto()
    envelope = crypto.encrypt(b"secret", aad=_aad(workspace_id="ws-a"))
    with pytest.raises(SecretCryptoError):
        crypto.decrypt(envelope, aad=_aad(workspace_id="ws-b"))


def test_aad_swap_schema_version_fails() -> None:
    crypto = _crypto()
    envelope = crypto.encrypt(b"secret", aad=_aad(schema_version=1))
    with pytest.raises(SecretCryptoError):
        crypto.decrypt(envelope, aad=_aad(schema_version=2))


def test_rejects_non_32_byte_master_key() -> None:
    with pytest.raises(SecretCryptoError):
        SecretCrypto(master_key=b"too-short", key_version=1)


def test_rejects_non_positive_key_version() -> None:
    with pytest.raises(SecretCryptoError):
        SecretCrypto(master_key=_key32(), key_version=0)


def test_repr_redacts_master_key() -> None:
    crypto = _crypto()
    text = repr(crypto)
    assert "\x01" not in text
    assert base64.b64encode(_key32()).decode() not in text
    assert "REDACTED" in text
