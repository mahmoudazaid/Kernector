"""Conversation id validation and scoped thread-key policy (#213)."""

from __future__ import annotations

import pytest

from application.errors import ApplicationValidationError, InputRejectedError
from application.thread_memory import (
    CONVERSATION_ID_CONTRACT,
    require_conversation_id,
    scoped_thread_key,
)


@pytest.mark.parametrize(
    "raw",
    [
        "conv-abc",
        "a" * 64,
        "550e8400-e29b-41d4-a716-446655440000",
        "Conv_1-2",
    ],
)
def test_require_conversation_id_accepts_valid_shapes(raw: str) -> None:
    assert require_conversation_id(raw) == raw


def test_require_conversation_id_strips_surrounding_whitespace() -> None:
    assert require_conversation_id("  conv-1  ") == "conv-1"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "bad:id",
        "bad/id",
        "has space",
        "a" * 65,
        "emoji😀",
        None,
        12,
    ],
)
def test_require_conversation_id_rejects_malformed(raw: object) -> None:
    with pytest.raises(InputRejectedError, match="conversation_id"):
        require_conversation_id(raw)  # type: ignore[arg-type]


def test_require_conversation_id_error_names_contract() -> None:
    with pytest.raises(InputRejectedError) as caught:
        require_conversation_id("bad:id")
    assert CONVERSATION_ID_CONTRACT in str(caught.value)


def test_scoped_thread_key_joins_with_colon() -> None:
    assert scoped_thread_key("ws-a", "conv-1") == "ws-a:conv-1"


def test_scoped_thread_key_is_unique_across_workspace_and_conversation() -> None:
    assert scoped_thread_key("ws-a", "conv-1") != scoped_thread_key("ws-b", "conv-1")
    assert scoped_thread_key("ws-a", "conv-1") != scoped_thread_key("ws-a", "conv-2")


def test_scoped_thread_key_rejects_blank_parts() -> None:
    with pytest.raises(InputRejectedError):
        scoped_thread_key("", "conv-1")
    with pytest.raises(InputRejectedError):
        scoped_thread_key("ws-a", "")
