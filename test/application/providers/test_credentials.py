"""Application credential lifecycle against a fake CredentialStore (#461)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest

from application.providers.credentials import (
    CreateWorkspaceCredential,
    CreateWorkspaceCredentialRequest,
    DisableWorkspaceCredential,
    GetActiveWorkspaceCredential,
    ListWorkspaceCredentials,
    ReplaceWorkspaceCredential,
    RevokeWorkspaceCredential,
    RotateWorkspaceCredential,
    key_hint_for_secret,
)
from domain.errors import UnknownProviderError
from domain.providers.credentials import (
    CredentialStatus,
    WorkspaceCredential,
    key_hint_for_secret as domain_key_hint,
)
from domain.providers.errors import CredentialConflictError, CredentialNotFoundError


@dataclass
class FakeCredentialStore:
    workspace_id: str = "ws-a"
    rows: dict[str, WorkspaceCredential] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, object]] = field(default_factory=list)
    clock: str = "2026-01-01T00:00:00+00:00"

    def insert_active(
        self,
        *,
        credential_id: str,
        provider: str,
        plaintext_secret: str,
        key_hint: str,
        created_by: str,
    ) -> WorkspaceCredential:
        self.calls.append(("insert_active", provider))
        for row in self.rows.values():
            if row.provider == provider and row.status == CredentialStatus.ACTIVE:
                raise CredentialConflictError(
                    "active credential already exists for provider"
                )
        meta = WorkspaceCredential(
            credential_id=credential_id,
            workspace_id=self.workspace_id,
            provider=provider,
            key_hint=key_hint,
            status=CredentialStatus.ACTIVE,
            encryption_key_version=1,
            created_by=created_by,
            created_at=self.clock,
            updated_at=self.clock,
            rotated_at=None,
        )
        self.rows[credential_id] = meta
        self.secrets[credential_id] = plaintext_secret
        return meta

    def replace_active_secret(
        self, provider: str, plaintext_secret: str, *, key_hint: str
    ) -> WorkspaceCredential:
        self.calls.append(("replace_active_secret", provider))
        active = self.get_active(provider)
        if active is None:
            raise CredentialNotFoundError("active credential not found")
        updated = replace(
            active,
            key_hint=key_hint,
            updated_at=self.clock,
        )
        self.rows[active.credential_id] = updated
        self.secrets[active.credential_id] = plaintext_secret
        return updated

    def rotate_active_secret(
        self, provider: str, plaintext_secret: str, *, key_hint: str
    ) -> WorkspaceCredential:
        self.calls.append(("rotate_active_secret", provider))
        active = self.get_active(provider)
        if active is None:
            raise CredentialNotFoundError("active credential not found")
        updated = replace(
            active,
            key_hint=key_hint,
            updated_at=self.clock,
            rotated_at=self.clock,
        )
        self.rows[active.credential_id] = updated
        self.secrets[active.credential_id] = plaintext_secret
        return updated

    def disable_active(self, provider: str) -> WorkspaceCredential:
        self.calls.append(("disable_active", provider))
        return self._set_status(provider, CredentialStatus.DISABLED)

    def revoke_active(self, provider: str) -> WorkspaceCredential:
        self.calls.append(("revoke_active", provider))
        return self._set_status(provider, CredentialStatus.REVOKED)

    def get_active(self, provider: str) -> WorkspaceCredential | None:
        for row in self.rows.values():
            if row.provider == provider and row.status == CredentialStatus.ACTIVE:
                return row
        return None

    def get(self, credential_id: str) -> WorkspaceCredential | None:
        return self.rows.get(credential_id)

    def list(self) -> tuple[WorkspaceCredential, ...]:
        return tuple(self.rows.values())

    def _set_status(
        self, provider: str, status: CredentialStatus
    ) -> WorkspaceCredential:
        active = self.get_active(provider)
        if active is None:
            raise CredentialNotFoundError("active credential not found")
        updated = replace(active, status=status, updated_at=self.clock)
        self.rows[active.credential_id] = updated
        return updated


def test_key_hint_empty_for_short_secrets() -> None:
    assert domain_key_hint("abcd") == ""
    assert domain_key_hint("abc") == ""
    assert domain_key_hint("abcde") == "bcde"
    assert key_hint_for_secret("abcdefgh") == "efgh"


def test_create_returns_metadata_never_secret() -> None:
    store = FakeCredentialStore()
    created = CreateWorkspaceCredential(store=store).execute(
        CreateWorkspaceCredentialRequest(
            provider="openrouter",
            plaintext_secret="test-openrouter-key-001",
            created_by="usr_admin",
        )
    )
    assert created.provider == "openrouter"
    assert created.key_hint == "-001"
    assert created.status == CredentialStatus.ACTIVE
    assert "test-openrouter-key-001" not in created.credential_id
    assert store.calls[0][0] == "insert_active"


def test_create_rejects_unknown_provider() -> None:
    store = FakeCredentialStore()
    with pytest.raises(UnknownProviderError):
        CreateWorkspaceCredential(store=store).execute(
            CreateWorkspaceCredentialRequest(
                provider="not-a-provider",
                plaintext_secret="test-openrouter-key-001",
                created_by="usr_admin",
            )
        )
    assert store.calls == []


def test_create_rejects_blank_secret() -> None:
    store = FakeCredentialStore()
    with pytest.raises(ValueError):
        CreateWorkspaceCredential(store=store).execute(
            CreateWorkspaceCredentialRequest(
                provider="openrouter",
                plaintext_secret="   ",
                created_by="usr_admin",
            )
        )


def test_create_conflict_when_active_exists() -> None:
    store = FakeCredentialStore()
    create = CreateWorkspaceCredential(store=store)
    request = CreateWorkspaceCredentialRequest(
        provider="openai",
        plaintext_secret="test-openai-primary-001",
        created_by="usr_admin",
    )
    create.execute(request)
    with pytest.raises(CredentialConflictError):
        create.execute(request)


def test_replace_does_not_set_rotated_at() -> None:
    store = FakeCredentialStore()
    CreateWorkspaceCredential(store=store).execute(
        CreateWorkspaceCredentialRequest(
            provider="anthropic",
            plaintext_secret="test-anthropic-key-001",
            created_by="usr_admin",
        )
    )
    updated = ReplaceWorkspaceCredential(store=store).execute(
        provider="anthropic",
        plaintext_secret="test-anthropic-key-002",
    )
    assert updated.rotated_at is None
    assert updated.key_hint == "-002"
    assert store.calls[-1][0] == "replace_active_secret"


def test_rotate_sets_rotated_at() -> None:
    store = FakeCredentialStore()
    CreateWorkspaceCredential(store=store).execute(
        CreateWorkspaceCredentialRequest(
            provider="gemini",
            plaintext_secret="test-gemini-key-0001",
            created_by="usr_admin",
        )
    )
    rotated = RotateWorkspaceCredential(store=store).execute(
        provider="gemini",
        plaintext_secret="test-gemini-key-0002",
    )
    assert rotated.rotated_at == store.clock
    assert store.calls[-1][0] == "rotate_active_secret"


def test_disable_and_revoke_only_from_active() -> None:
    store = FakeCredentialStore()
    CreateWorkspaceCredential(store=store).execute(
        CreateWorkspaceCredentialRequest(
            provider="ollama",
            plaintext_secret="test-ollama-token-001",
            created_by="usr_admin",
        )
    )
    disabled = DisableWorkspaceCredential(store=store).execute("ollama")
    assert disabled.status == CredentialStatus.DISABLED
    with pytest.raises(CredentialNotFoundError):
        RevokeWorkspaceCredential(store=store).execute("ollama")


def test_revoke_from_active() -> None:
    store = FakeCredentialStore()
    CreateWorkspaceCredential(store=store).execute(
        CreateWorkspaceCredentialRequest(
            provider="openrouter",
            plaintext_secret="test-openrouter-key-001",
            created_by="usr_admin",
        )
    )
    revoked = RevokeWorkspaceCredential(store=store).execute("openrouter")
    assert revoked.status == CredentialStatus.REVOKED


def test_get_active_and_list_metadata_only() -> None:
    store = FakeCredentialStore()
    created = CreateWorkspaceCredential(store=store).execute(
        CreateWorkspaceCredentialRequest(
            provider="openai",
            plaintext_secret="test-openai-primary-001",
            created_by="usr_admin",
        )
    )
    assert GetActiveWorkspaceCredential(store=store).execute("openai") == created
    listed = ListWorkspaceCredentials(store=store).execute()
    assert listed == (created,)
