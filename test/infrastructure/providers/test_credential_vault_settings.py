"""Credential vault Settings loading and fail-closed crypto construction (#461)."""

from __future__ import annotations

import base64

import pytest

from infrastructure.config import load_settings
from infrastructure.providers.secret_crypto import (
    SecretCryptoError,
    secret_crypto_from_vault_settings,
)


def _b64_key(seed: bytes = b"\x33" * 32) -> str:
    return base64.b64encode(seed).decode("ascii")


def test_settings_omit_vault_key_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORKSPACE_CREDENTIAL_MASTER_KEY", raising=False)
    monkeypatch.delenv("WORKSPACE_CREDENTIAL_MASTER_KEY_VERSION", raising=False)
    vault = load_settings().credential_vault
    assert vault.master_key is None
    assert vault.key_version is None
    assert "master_key=None" in repr(vault)


def test_settings_load_valid_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    key = _b64_key()
    monkeypatch.setenv("WORKSPACE_CREDENTIAL_MASTER_KEY", key)
    monkeypatch.setenv("WORKSPACE_CREDENTIAL_MASTER_KEY_VERSION", "3")
    vault = load_settings().credential_vault
    assert vault.master_key == b"\x33" * 32
    assert vault.key_version == 3
    assert key not in repr(vault)
    assert "REDACTED" in repr(vault)


def test_settings_reject_partial_vault_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSPACE_CREDENTIAL_MASTER_KEY", _b64_key())
    monkeypatch.delenv("WORKSPACE_CREDENTIAL_MASTER_KEY_VERSION", raising=False)
    with pytest.raises(ValueError, match="together"):
        load_settings()


def test_settings_reject_wrong_key_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "WORKSPACE_CREDENTIAL_MASTER_KEY",
        base64.b64encode(b"short").decode("ascii"),
    )
    monkeypatch.setenv("WORKSPACE_CREDENTIAL_MASTER_KEY_VERSION", "1")
    with pytest.raises(ValueError, match="32 bytes"):
        load_settings()


def test_secret_crypto_from_settings_fails_closed_when_missing() -> None:
    with pytest.raises(SecretCryptoError):
        secret_crypto_from_vault_settings(None, None)
