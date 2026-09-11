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


def test_agent_turn_result_accepts_content_and_steps() -> None:
    from domain.models import AgentTurnResult

    result = AgentTurnResult(content="done", steps=2)
    assert result.content == "done"
    assert result.steps == 2


@pytest.mark.parametrize("blank", ["", "   "])
def test_agent_turn_result_rejects_blank_content(blank: str) -> None:
    from domain.models import AgentTurnResult

    with pytest.raises(DomainValidationError, match="content"):
        AgentTurnResult(content=blank)


def test_agent_turn_result_rejects_non_string_content() -> None:
    from domain.models import AgentTurnResult

    with pytest.raises(DomainValidationError, match="content"):
        AgentTurnResult(content=123)  # type: ignore[arg-type]


def test_agent_turn_result_rejects_negative_steps() -> None:
    from domain.models import AgentTurnResult

    with pytest.raises(DomainValidationError, match="steps"):
        AgentTurnResult(content="ok", steps=-1)


def test_agent_turn_result_rejects_bool_steps() -> None:
    from domain.models import AgentTurnResult

    with pytest.raises(DomainValidationError, match="steps"):
        AgentTurnResult(content="ok", steps=True)  # type: ignore[arg-type]


def test_agent_turn_result_accepts_truncated_flag() -> None:
    from domain.models import AgentTurnResult

    result = AgentTurnResult(content="Stopped", truncated=True)
    assert result.truncated is True


def test_agent_turn_result_rejects_non_bool_truncated() -> None:
    from domain.models import AgentTurnResult

    with pytest.raises(DomainValidationError, match="truncated"):
        AgentTurnResult(content="ok", truncated=1)  # type: ignore[arg-type]
