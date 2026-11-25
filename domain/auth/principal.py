"""Authenticated principal identity (#182)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


def new_user_id() -> str:
    """Return a fresh opaque user id stable across sessions for one account."""
    return f"usr_{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class Principal:
    """Server-side authenticated actor.

    ``user_id`` is immutable and stable across sessions for the same account
    so later workspace membership (#446) can key on it.
    """

    user_id: str
    username: str
