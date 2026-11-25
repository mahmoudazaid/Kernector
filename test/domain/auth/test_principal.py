"""Domain Principal (#182)."""

from __future__ import annotations

import dataclasses

import pytest

from domain.auth.principal import Principal, new_user_id


def test_principal_is_frozen_with_immutable_user_id() -> None:
    user_id = new_user_id()
    principal = Principal(user_id=user_id, username="alice")
    assert principal.user_id == user_id
    assert principal.username == "alice"
    with pytest.raises(dataclasses.FrozenInstanceError):
        principal.user_id = "mutated"  # type: ignore[misc]


def test_new_user_id_is_opaque_and_unique() -> None:
    first = new_user_id()
    second = new_user_id()
    assert first != second
    assert first.startswith("usr_")
