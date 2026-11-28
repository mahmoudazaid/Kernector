"""Workspace AI credential metadata models (#461)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

_KEY_HINT_SUFFIX_LEN = 4


class CredentialStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    REVOKED = "revoked"


def new_credential_id() -> str:
    """Return a fresh opaque credential id."""
    return f"cred_{uuid.uuid4().hex}"


def key_hint_for_secret(plaintext_secret: str) -> str:
    """Return a non-identifying suffix hint, or empty when it would equal the secret.

    Short secrets (length <= suffix length) must not expose the complete value
    as ``key_hint``.
    """
    if not isinstance(plaintext_secret, str):
        return ""
    if len(plaintext_secret) <= _KEY_HINT_SUFFIX_LEN:
        return ""
    return plaintext_secret[-_KEY_HINT_SUFFIX_LEN:]


@dataclass(frozen=True, slots=True)
class WorkspaceCredential:
    """Sanitized credential metadata — never carries plaintext or ciphertext."""

    credential_id: str
    workspace_id: str
    provider: str
    key_hint: str
    status: CredentialStatus
    encryption_key_version: int
    created_by: str
    created_at: str
    updated_at: str
    rotated_at: str | None = None
