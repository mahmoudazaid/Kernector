"""Minimal acceptance: use cases + real store + reveal (#461).

Test-only glue — not a fifth production seam.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from application.providers.credentials import (
    CreateWorkspaceCredential,
    CreateWorkspaceCredentialRequest,
    RotateWorkspaceCredential,
)
from domain.providers.credentials import CredentialStatus
from infrastructure.providers.secret_crypto import SecretCrypto
from infrastructure.providers.sql_reveal import SqlCredentialSecretReveal
from infrastructure.providers.sql_store import SqlCredentialStore


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    return tmp_path / "catalog.sqlite"


@pytest.fixture
def crypto() -> SecretCrypto:
    return SecretCrypto(master_key=b"\x44" * 32, key_version=1)


def test_create_rotate_reveal_new_secret_old_blob_unreachable(
    catalog_path: Path, crypto: SecretCrypto
) -> None:
    store = SqlCredentialStore(catalog_path, "ws-a", crypto=crypto)
    reveal = SqlCredentialSecretReveal(catalog_path, "ws-a", crypto=crypto)
    old_secret = "test-acceptance-old-secret-aaa"
    new_secret = "test-acceptance-new-secret-bbb"

    created = CreateWorkspaceCredential(store=store).execute(
        CreateWorkspaceCredentialRequest(
            provider="openrouter",
            plaintext_secret=old_secret,
            created_by="usr_admin",
        )
    )
    assert reveal.reveal_active_secret("openrouter") == old_secret

    connection = sqlite3.connect(catalog_path)
    try:
        old_blob = connection.execute(
            "SELECT encrypted_secret FROM workspace_ai_credentials WHERE id = ?",
            (created.credential_id,),
        ).fetchone()[0]
    finally:
        connection.close()

    rotated = RotateWorkspaceCredential(store=store).execute(
        provider="openrouter",
        plaintext_secret=new_secret,
    )
    assert rotated.status == CredentialStatus.ACTIVE
    assert rotated.rotated_at is not None
    assert reveal.reveal_active_secret("openrouter") == new_secret

    connection = sqlite3.connect(catalog_path)
    try:
        row = connection.execute(
            "SELECT encrypted_secret FROM workspace_ai_credentials WHERE id = ?",
            (created.credential_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    assert bytes(row[0]) != bytes(old_blob)
    assert old_secret.encode("utf-8") not in bytes(row[0])
