"""Application wrappers for short-term thread memory identity (#213)."""

from __future__ import annotations

from application.errors import InputRejectedError
from domain.thread_memory import (
    CONVERSATION_ID_CONTRACT,
    require_conversation_id as _domain_require_conversation_id,
    scoped_thread_key as _domain_scoped_thread_key,
)

__all__ = [
    "CONVERSATION_ID_CONTRACT",
    "require_conversation_id",
    "scoped_thread_key",
]


def require_conversation_id(raw: object) -> str:
    """Validate a client conversation id as ``InputRejectedError`` (422)."""
    try:
        return _domain_require_conversation_id(raw)
    except ValueError as error:
        raise InputRejectedError(str(error)) from error


def scoped_thread_key(workspace_id: str, conversation_id: str) -> str:
    """Build the scoped LangGraph thread key after validating conversation id."""
    try:
        return _domain_scoped_thread_key(workspace_id, conversation_id)
    except ValueError as error:
        raise InputRejectedError(str(error)) from error
