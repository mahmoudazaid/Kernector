"""Runtime validation for domain conversation messages."""

import pytest

from domain.errors import DomainValidationError
from domain.models import Message


def test_message_constructs_with_valid_role_and_content() -> None:
    message = Message(role="user", content="How do I restart?")
    assert message.role == "user"
    assert message.content == "How do I restart?"


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_message_rejects_blank_content(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="content"):
        Message(role="user", content=blank)


def test_message_rejects_non_string_content() -> None:
    sentinel = "CONTENT-LEAK-SENTINEL"
    with pytest.raises(DomainValidationError) as raised:
        Message(role="user", content=[sentinel])  # type: ignore[arg-type]
    message = str(raised.value)
    assert sentinel not in message
    assert message == "content must be a non-empty string, got list"


def test_message_rejects_invalid_role() -> None:
    with pytest.raises(DomainValidationError, match="role"):
        Message(role="narrator", content="hi")  # type: ignore[arg-type]


def test_message_rejects_invalid_role_without_echoing_value() -> None:
    sentinel = "ROLE-LEAK-SENTINEL-" + ("x" * 40)
    with pytest.raises(DomainValidationError) as raised:
        Message(role=sentinel, content="hi")  # type: ignore[arg-type]
    message = str(raised.value)
    assert sentinel not in message
    assert "system" in message
    assert "user" in message
    assert "assistant" in message


def test_message_rejects_non_string_role() -> None:
    with pytest.raises(DomainValidationError, match="role"):
        Message(role=1, content="hi")  # type: ignore[arg-type]
