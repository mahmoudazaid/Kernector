"""Errors for workspace AI credential vault operations (#461)."""

from __future__ import annotations


class CredentialVaultError(Exception):
    """Base for credential vault failures (sanitized messages only)."""


class CredentialConflictError(CredentialVaultError):
    """An active credential already exists for the provider, or a write conflicted."""


class CredentialNotFoundError(CredentialVaultError):
    """No matching credential for the requested lookup or active mutation."""


class CredentialInactiveError(CredentialVaultError):
    """The credential exists but is not active for the requested operation."""
