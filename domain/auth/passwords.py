"""Versioned scrypt password hashing (#182)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
SCRYPT_MAXMEM = 32 * 1024 * 1024
_SALT_BYTES = 16
_VERSION = "v1"


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    """Return a ``scrypt$v1$…`` encoding of *password*."""
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM,
    )
    return (
        f"scrypt${_VERSION}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}"
        f"${_b64encode(salt)}${_b64encode(derived)}"
    )


def verify_password(password: str, encoded: str) -> bool:
    """Return whether *password* matches a versioned scrypt encoding."""
    parts = encoded.split("$")
    if len(parts) != 7 or parts[0] != "scrypt" or parts[1] != _VERSION:
        return False
    try:
        n = int(parts[2])
        r = int(parts[3])
        p = int(parts[4])
        salt = _b64decode(parts[5])
        expected = _b64decode(parts[6])
    except (ValueError, TypeError):
        return False
    if n != SCRYPT_N or r != SCRYPT_R or p != SCRYPT_P:
        return False
    if len(expected) != SCRYPT_DKLEN:
        return False
    try:
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=SCRYPT_DKLEN,
            maxmem=SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(derived, expected)
