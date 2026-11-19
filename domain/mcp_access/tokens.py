"""Cryptographic helpers for MCP access-profile tokens (#324)."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_access_token() -> str:
    """Return a cryptographically secure opaque bearer token."""
    return secrets.token_urlsafe(32)


def hash_access_token(plaintext_token: str) -> str:
    """Return a SHA-256 hex digest of *plaintext_token* for at-rest storage."""
    return hashlib.sha256(plaintext_token.encode("utf-8")).hexdigest()


def tokens_match(plaintext_token: str, token_hash: str) -> bool:
    """Constant-time compare of *plaintext_token* against a stored hash."""
    return hmac.compare_digest(hash_access_token(plaintext_token), token_hash)
