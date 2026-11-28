"""SqlCredentialSecretReveal contract (#461)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from domain.providers.credentials import CredentialStatus
from domain.providers.errors import CredentialNotFoundError
from infrastructure.providers.secret_crypto import SecretCrypto, SecretCryptoError
from infrastructure.providers.sql_reveal import SqlCredentialSecretReveal
from infrastructure.providers.sql_store import SqlCredentialStore


def _key() -> bytes:
    return b"\x22" * 32


def _crypto() -> SecretCrypto:
    return SecretCrypto(master_key=_key(), key_version=1)


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    return tmp_path / "catalog.sqlite"


@pytest.fixture
def store(catalog_path: Path) -> SqlCredentialStore:
    return SqlCredentialStore(catalog_path, "ws-a", crypto=_crypto())


@pytest.fixture
def reveal(catalog_path: Path) -> SqlCredentialSecretReveal:
    return SqlCredentialSecretReveal(catalog_path, "ws-a", crypto=_crypto())


def test_reveal_active_secret_round_trip(
    store: SqlCredentialStore, reveal: SqlCredentialSecretReveal
) -> None:
    secret = "test-reveal-round-trip-secret"
    store.insert_active(
        credential_id="cred_1",
        provider="openrouter",
        plaintext_secret=secret,
        key_hint="cret",
        created_by="usr_admin",
    )
    assert reveal.reveal_active_secret("openrouter") == secret


def test_reveal_missing_fails(reveal: SqlCredentialSecretReveal) -> None:
    with pytest.raises(CredentialNotFoundError):
        reveal.reveal_active_secret("openrouter")


def test_reveal_disabled_fails(
    store: SqlCredentialStore, reveal: SqlCredentialSecretReveal
) -> None:
    store.insert_active(
        credential_id="cred_1",
        provider="openai",
        plaintext_secret="test-disabled-secret-value",
        key_hint="alue",
        created_by="usr_admin",
    )
    store.disable_active("openai")
    with pytest.raises(CredentialNotFoundError):
        reveal.reveal_active_secret("openai")


def test_reveal_revoked_fails(
    store: SqlCredentialStore, reveal: SqlCredentialSecretReveal
) -> None:
    store.insert_active(
        credential_id="cred_1",
        provider="anthropic",
        plaintext_secret="test-revoked-secret-value1",
        key_hint="ue1",
        created_by="usr_admin",
    )
    store.revoke_active("anthropic")
    with pytest.raises(CredentialNotFoundError):
        reveal.reveal_active_secret("anthropic")


def test_after_rotate_reveal_returns_new_secret_only(
    store: SqlCredentialStore,
    reveal: SqlCredentialSecretReveal,
    catalog_path: Path,
) -> None:
    old_secret = "test-old-secret-value-aaaa"
    new_secret = "test-new-secret-value-bbbb"
    store.insert_active(
        credential_id="cred_1",
        provider="gemini",
        plaintext_secret=old_secret,
        key_hint="aaaa",
        created_by="usr_admin",
    )
    connection = sqlite3.connect(catalog_path)
    try:
        old_blob = connection.execute(
            "SELECT encrypted_secret FROM workspace_ai_credentials WHERE id = ?",
            ("cred_1",),
        ).fetchone()[0]
    finally:
        connection.close()

    store.rotate_active_secret("gemini", new_secret, key_hint="bbbb")
    assert reveal.reveal_active_secret("gemini") == new_secret

    connection = sqlite3.connect(catalog_path)
    try:
        row = connection.execute(
            "SELECT encrypted_secret, status FROM workspace_ai_credentials WHERE id = ?",
            ("cred_1",),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    assert bytes(row[0]) != bytes(old_blob)
    assert old_secret.encode("utf-8") not in bytes(row[0])
    assert row[1] == CredentialStatus.ACTIVE.value


def test_store_metadata_still_excludes_plaintext(
    store: SqlCredentialStore, reveal: SqlCredentialSecretReveal
) -> None:
    secret = "test-meta-check-secret-zzzz"
    created = store.insert_active(
        credential_id="cred_1",
        provider="ollama",
        plaintext_secret=secret,
        key_hint="zzzz",
        created_by="usr_admin",
    )
    assert secret not in repr(created)
    assert secret not in repr(store.get_active("ollama"))
    assert secret not in repr(store.list())
    assert reveal.reveal_active_secret("ollama") == secret


def test_tampered_ciphertext_fails_closed(
    store: SqlCredentialStore,
    reveal: SqlCredentialSecretReveal,
    catalog_path: Path,
) -> None:
    store.insert_active(
        credential_id="cred_1",
        provider="openrouter",
        plaintext_secret="test-tamper-check-secret-1",
        key_hint="et-1",
        created_by="usr_admin",
    )
    connection = sqlite3.connect(catalog_path)
    try:
        blob = connection.execute(
            "SELECT encrypted_secret FROM workspace_ai_credentials WHERE id = ?",
            ("cred_1",),
        ).fetchone()[0]
        tampered = bytes([blob[0] ^ 0xFF]) + blob[1:]
        connection.execute(
            "UPDATE workspace_ai_credentials SET encrypted_secret = ? WHERE id = ?",
            (tampered, "cred_1"),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises((SecretCryptoError, CredentialNotFoundError, RuntimeError)):
        reveal.reveal_active_secret("openrouter")
