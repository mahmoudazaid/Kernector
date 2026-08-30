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
    with pytest.raises(DomainValidationError, match="content"):
        Message(role="user", content=123)  # type: ignore[arg-type]


def test_message_rejects_invalid_role() -> None:
    with pytest.raises(DomainValidationError, match="role"):
        Message(role="narrator", content="hi")  # type: ignore[arg-type]


def test_message_rejects_non_string_role() -> None:
    with pytest.raises(DomainValidationError, match="role"):
        Message(role=1, content="hi")  # type: ignore[arg-type]
