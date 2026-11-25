"""Domain password hashing (#182)."""

from __future__ import annotations

import pytest

from domain.auth.passwords import (
    SCRYPT_DKLEN,
    SCRYPT_MAXMEM,
    SCRYPT_N,
    SCRYPT_P,
    SCRYPT_R,
    hash_password,
    verify_password,
)


def test_hash_password_uses_versioned_scrypt_v1_format() -> None:
    encoded = hash_password("correct-horse")
    parts = encoded.split("$")
    assert parts[0] == "scrypt"
    assert parts[1] == "v1"
    assert parts[2] == str(SCRYPT_N)
    assert parts[3] == str(SCRYPT_R)
    assert parts[4] == str(SCRYPT_P)
    assert parts[5]
    assert parts[6]


def test_hash_password_uses_documented_scrypt_parameters() -> None:
    assert SCRYPT_N == 16384
    assert SCRYPT_R == 8
    assert SCRYPT_P == 1
    assert SCRYPT_DKLEN == 64
    assert SCRYPT_MAXMEM == 32 * 1024 * 1024


def test_verify_password_accepts_matching_secret() -> None:
    encoded = hash_password("correct-horse")
    assert verify_password("correct-horse", encoded) is True


def test_verify_password_rejects_wrong_secret() -> None:
    encoded = hash_password("correct-horse")
    assert verify_password("wrong-battery", encoded) is False


def test_verify_password_rejects_unknown_version() -> None:
    encoded = hash_password("correct-horse")
    mangled = encoded.replace("$v1$", "$v99$", 1)
    assert verify_password("correct-horse", mangled) is False


def test_hash_password_uses_unique_salts() -> None:
    first = hash_password("same-password")
    second = hash_password("same-password")
    assert first != second


def test_verify_password_rejects_malformed_encoding() -> None:
    assert verify_password("x", "not-a-hash") is False
    assert verify_password("x", "scrypt$v1$1$2") is False
