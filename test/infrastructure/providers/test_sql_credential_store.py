"""SqlCredentialStore persistence contract (#461)."""

from __future__ import annotations

import sqlite3
from dataclasses import astuple
from pathlib import Path

import pytest

from domain.providers.credentials import CredentialStatus, WorkspaceCredential
from domain.providers.errors import CredentialConflictError, CredentialNotFoundError
from infrastructure.providers.secret_crypto import SecretCrypto
from infrastructure.providers.sql_store import SqlCredentialStore


def _key() -> bytes:
    return b"\x11" * 32


def _crypto() -> SecretCrypto:
    return SecretCrypto(master_key=_key(), key_version=1)


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    return tmp_path / "catalog.sqlite"


@pytest.fixture
def store(catalog_path: Path) -> SqlCredentialStore:
    return SqlCredentialStore(catalog_path, "ws-a", crypto=_crypto())


def _insert(
    store: SqlCredentialStore,
    *,
    credential_id: str = "cred_1",
    provider: str = "openrouter",
    secret: str = "test-super-secret-value",
    key_hint: str = "alue",
    created_by: str = "usr_admin",
) -> WorkspaceCredential:
    return store.insert_active(
        credential_id=credential_id,
        provider=provider,
        plaintext_secret=secret,
        key_hint=key_hint,
        created_by=created_by,
    )


def test_insert_and_get_active_return_metadata_only(store: SqlCredentialStore) -> None:
    created = _insert(store)
    assert created.status == CredentialStatus.ACTIVE
    assert created.workspace_id == "ws-a"
    assert created.provider == "openrouter"
    assert created.key_hint == "alue"
    assert created.rotated_at is None
    assert "test-super-secret-value" not in repr(created)
    assert "test-super-secret-value" not in astuple(created)

    fetched = store.get_active("openrouter")
    assert fetched == created
    assert fetched is not None
    assert "test-super-secret-value" not in astuple(fetched)


def test_get_by_id_and_list(store: SqlCredentialStore) -> None:
    created = _insert(store)
    assert store.get("cred_1") == created
    assert store.list() == (created,)


def test_ciphertext_not_plaintext_at_rest(
    store: SqlCredentialStore, catalog_path: Path
) -> None:
    secret = "test-super-secret-value"
    _insert(store, secret=secret)
    connection = sqlite3.connect(catalog_path)
    try:
        row = connection.execute(
            "SELECT encrypted_secret, nonce FROM workspace_ai_credentials "
            "WHERE id = ?",
            ("cred_1",),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    encrypted, nonce = row
    assert isinstance(encrypted, (bytes, memoryview))
    assert bytes(encrypted) != secret.encode("utf-8")
    assert secret.encode("utf-8") not in bytes(encrypted)
    assert len(bytes(nonce)) == 12


def test_duplicate_active_raises_conflict(store: SqlCredentialStore) -> None:
    _insert(store)
    with pytest.raises(CredentialConflictError):
        _insert(store, credential_id="cred_2", secret="another-secret-value")


def test_replace_active_does_not_set_rotated_at(store: SqlCredentialStore) -> None:
    _insert(store)
    updated = store.replace_active_secret(
        "openrouter", "test-replacement-secret-xx", key_hint="t-xx"
    )
    assert updated.status == CredentialStatus.ACTIVE
    assert updated.rotated_at is None
    assert updated.key_hint == "t-xx"


def test_rotate_active_sets_rotated_at(store: SqlCredentialStore) -> None:
    _insert(store)
    rotated = store.rotate_active_secret(
        "openrouter", "test-rotated-secret-value", key_hint="alue"
    )
    assert rotated.status == CredentialStatus.ACTIVE
    assert rotated.rotated_at is not None


def test_rewrite_fails_when_active_row_swapped(
    store: SqlCredentialStore, catalog_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _insert(store, credential_id="cred_1", secret="secret-one-aaaa", key_hint="aaaa")
    real_get_active = store.get_active

    def get_active_then_swap(provider: str) -> WorkspaceCredential | None:
        active = real_get_active(provider)
        store.revoke_active(provider)
        store.insert_active(
            credential_id="cred_2",
            provider=provider,
            plaintext_secret="secret-two-bbbb",
            key_hint="bbbb",
            created_by="usr_admin",
        )
        return active

    monkeypatch.setattr(store, "get_active", get_active_then_swap)
    with pytest.raises(CredentialNotFoundError):
        store.rotate_active_secret(
            "openrouter", "secret-three-cccc", key_hint="cccc"
        )

    active = SqlCredentialStore(catalog_path, "ws-a", crypto=_crypto()).get_active(
        "openrouter"
    )
    assert active is not None
    assert active.credential_id == "cred_2"
    assert active.key_hint == "bbbb"


def test_replace_when_missing_raises_not_found(store: SqlCredentialStore) -> None:
    with pytest.raises(CredentialNotFoundError):
        store.replace_active_secret(
            "openrouter", "test-missing-secret-xxxx", key_hint="xxxx"
        )


def test_disable_and_revoke_require_active(store: SqlCredentialStore) -> None:
    _insert(store)
    disabled = store.disable_active("openrouter")
    assert disabled.status == CredentialStatus.DISABLED
    assert store.get_active("openrouter") is None
    assert store.get("cred_1") is not None
    with pytest.raises(CredentialNotFoundError):
        store.revoke_active("openrouter")


def test_revoke_active(store: SqlCredentialStore) -> None:
    _insert(store)
    revoked = store.revoke_active("openrouter")
    assert revoked.status == CredentialStatus.REVOKED
    assert store.get_active("openrouter") is None


def test_workspace_isolation(catalog_path: Path) -> None:
    crypto = _crypto()
    store_a = SqlCredentialStore(catalog_path, "ws-a", crypto=crypto)
    store_b = SqlCredentialStore(catalog_path, "ws-b", crypto=crypto)
    _insert(store_a, secret="test-workspace-a-secret-1")
    assert store_b.get_active("openrouter") is None
    assert store_b.list() == ()
    _insert(store_b, credential_id="cred_b", secret="test-workspace-b-secret-1")
    assert store_a.get("cred_b") is None
    assert len(store_a.list()) == 1
    assert len(store_b.list()) == 1


def test_constructor_rejects_blank_workspace(catalog_path: Path) -> None:
    with pytest.raises(ValueError):
        SqlCredentialStore(catalog_path, "  ", crypto=_crypto())
