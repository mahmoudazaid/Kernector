"""Pure thread-memory identity helpers (no LangGraph).

Used by application validation wrappers and infrastructure adapters so
workspace and conversation keys cannot drift.
"""

from __future__ import annotations

import re

# fullmatch is load-bearing: .match()/.search() would accept injection prefixes.
_CONVERSATION_ID = re.compile(r"[A-Za-z0-9_-]+")
_MAX_CONVERSATION_ID_LENGTH = 64
CONVERSATION_ID_CONTRACT = (
    "must fullmatch [A-Za-z0-9_-]+ and be at most 64 characters"
)


def require_conversation_id(raw: object) -> str:
    """Validate a client-supplied conversation id.

    Raises:
        ValueError: Absent, wrong type, or contract failure. Message names
            ``conversation_id``.
    """
    if not isinstance(raw, str):
        raise ValueError(
            f"conversation_id must be a non-empty string, got {type(raw).__name__}"
        )
    value = raw.strip()
    if not value:
        raise ValueError("conversation_id must be non-empty")
    if len(value) > _MAX_CONVERSATION_ID_LENGTH or not _CONVERSATION_ID.fullmatch(
        value
    ):
        raise ValueError(f"conversation_id {CONVERSATION_ID_CONTRACT}")
    return value


def scoped_thread_key(workspace_id: str, conversation_id: str) -> str:
    """Return ``{workspace_id}:{conversation_id}`` for LangGraph ``thread_id``.

    ``conversation_id`` is validated with :func:`require_conversation_id`.
    ``workspace_id`` must be a non-blank string (server-validated upstream).

    Raises:
        ValueError: Either part is blank or ``conversation_id`` fails its contract.
    """
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise ValueError("workspace_id must be a non-empty string")
    conversation = require_conversation_id(conversation_id)
    return f"{workspace_id.strip()}:{conversation}"
