"""AskGeneral: labelled non-RAG answers via ChatModel only."""

from application.ask_general import AskGeneral
from application.ask_service import AskService
from application.contracts import AskRequest, RunMeta
from application.general_answer_policy import GENERAL_ANSWER_SYSTEM
from application.response_style_policy import ResponseStyle, compose_agent_system
from application.turn_routing import (
    CONFIDENCE_GENERAL,
    RoutingKind,
)
from domain.models import AskResult, Message, Usage


class _RecordingChat:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Message, ...], object]] = []
        self.result = AskResult(
            content="Here are three taglines.",
            model="test-model",
            latency_ms=12,
            usage=Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
            settings={},
        )

    def complete(self, system, messages, settings):  # noqa: ANN001
        self.calls.append((system, tuple(messages), settings))
        return self.result


def test_ask_general_uses_chat_model_without_citations() -> None:
    chat = _RecordingChat()
    ask = AskGeneral(AskService(chat))
    response = ask.execute(
        AskRequest(query="Brainstorm three creative taglines for a coffee brand")
    )
    assert response.answer == "Here are three taglines."
    assert response.citations == ()
    assert response.generation_hits == ()
    assert len(chat.calls) == 1
    system, messages, _settings = chat.calls[0]
    assert system == GENERAL_ANSWER_SYSTEM
    assert messages[-1].role == "user"
    assert "coffee brand" in messages[-1].content


def test_ask_general_run_meta_is_labelled_general_answer() -> None:
    chat = _RecordingChat()
    ask = AskGeneral(AskService(chat))
    response = ask.execute(AskRequest(query="Rewrite this sentence more clearly: hi"))
    assert response.run is not None
    assert response.run.path == "general_answer"
    assert response.run.intent == RoutingKind.GENERAL_ANSWER.value
    assert response.run.routing_confidence == CONFIDENCE_GENERAL
    assert response.run.ambiguous is False
    assert response.run.outcome == "success"
    assert response.run.citation_count == 0
    assert response.run.hit_count == 0


def test_general_answer_system_refuses_project_facts() -> None:
    assert "not grounded" in GENERAL_ANSWER_SYSTEM.lower() or "not from project" in GENERAL_ANSWER_SYSTEM.lower() or "project" in GENERAL_ANSWER_SYSTEM.lower()
    assert "must not" in GENERAL_ANSWER_SYSTEM.lower() or "do not" in GENERAL_ANSWER_SYSTEM.lower()
    lowered = GENERAL_ANSWER_SYSTEM.lower()
    assert "repository" in lowered or "project" in lowered or "source" in lowered


def test_ask_general_applies_response_style_to_system_prompt() -> None:
    chat = _RecordingChat()
    ask = AskGeneral(AskService(chat))
    response = ask.execute(
        AskRequest(
            query="brainstorm taglines",
            response_style=ResponseStyle.CONCISE,
        )
    )
    system, _messages, _settings = chat.calls[0]
    assert system == compose_agent_system(
        GENERAL_ANSWER_SYSTEM, ResponseStyle.CONCISE
    )
    assert "Response style" in system
    assert response.run is not None
    assert response.run.response_style == ResponseStyle.CONCISE.value


def test_ask_general_forwards_history_to_chat_model() -> None:
    chat = _RecordingChat()
    ask = AskGeneral(AskService(chat))
    history = (Message(role="user", content="Earlier context"),)
    ask.execute(AskRequest(query="Continue brainstorming", history=history))
    _system, messages, _settings = chat.calls[0]
    assert messages[0].content == "Earlier context"
    assert messages[-1].content == "Continue brainstorming"


def test_run_meta_accepts_routing_fields() -> None:
    meta = RunMeta(
        intent="general_answer",
        routing_confidence=0.75,
        ambiguous=False,
        path="general_answer",
        outcome="success",
    )
    assert meta.intent == "general_answer"
    assert meta.routing_confidence == 0.75
    assert meta.ambiguous is False
