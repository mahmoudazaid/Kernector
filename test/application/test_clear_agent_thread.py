"""Tests for ClearAgentThread and LangGraph thread-memory clear isolation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from application.errors import ApplicationValidationError, InputRejectedError
from application.run_tool_agent import ClearAgentThread, RunToolAgent
from application.untrusted_text import agent_tool_system_prompt
from domain.models import AgentTurnResult
from domain.ports import Tool

_SYSTEM = agent_tool_system_prompt()


class _FakeAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...], int, str | None]] = []

    def run(
        self,
        goal: str,
        tools: Sequence[Tool],
        *,
        max_steps: int,
        conversation_id: str | None = None,
    ) -> AgentTurnResult:
        self.calls.append(
            (goal, tuple(t.name for t in tools), max_steps, conversation_id)
        )
        return AgentTurnResult(content="done", steps=1)


class _FakeThreadMemory:
    def __init__(self) -> None:
        self.cleared: list[str] = []

    def clear(self, *, conversation_id: str) -> None:
        self.cleared.append(conversation_id)


class _Tool:
    @property
    def name(self) -> str:
        return "t"

    @property
    def description(self) -> str:
        return "tool"

    def run(self, arguments: Mapping[str, object]) -> str:
        return "ok"


def test_run_tool_agent_forwards_conversation_id() -> None:
    agent = _FakeAgent()
    RunToolAgent(agent).execute(
        "goal", [_Tool()], max_steps=2, conversation_id="conv-9"
    )
    assert agent.calls == [("goal", ("t",), 2, "conv-9")]


def test_run_tool_agent_rejects_blank_conversation_id() -> None:
    with pytest.raises(InputRejectedError, match="conversation_id"):
        RunToolAgent(_FakeAgent()).execute(
            "goal", [_Tool()], max_steps=1, conversation_id="  "
        )


def test_clear_agent_thread_delegates_and_is_idempotent() -> None:
    memory = _FakeThreadMemory()
    use_case = ClearAgentThread(memory)
    use_case.execute(conversation_id="conv-1")
    use_case.execute(conversation_id="conv-1")
    assert memory.cleared == ["conv-1", "conv-1"]


def test_clear_agent_thread_rejects_malformed_conversation_id() -> None:
    with pytest.raises(InputRejectedError, match="conversation_id"):
        ClearAgentThread(_FakeThreadMemory()).execute(conversation_id="bad:id")


def test_langgraph_clear_isolates_workspaces_on_shared_saver() -> None:
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver

    from infrastructure.agents.langgraph_tool_agent import (
        LangGraphThreadMemory,
        LangGraphToolAgent,
    )
    from test.infrastructure.agents.test_langgraph_tool_agent import (
        _RecordingFactory,
        _RecordingTool,
        _ScriptedChat,
        _ai_text,
    )

    saver = InMemorySaver()
    chat = _ScriptedChat([_ai_text("a"), _ai_text("b"), _ai_text("reuse-a")])
    factory = _RecordingFactory(chat)
    agent_a = LangGraphToolAgent(
        system_prompt=_SYSTEM,
        model_factory=factory,
        checkpointer=saver,
        workspace_id="ws-a",
    )
    agent_b = LangGraphToolAgent(
        system_prompt=_SYSTEM,
        model_factory=factory,
        checkpointer=saver,
        workspace_id="ws-b",
    )
    agent_a.run("keep-a", [_RecordingTool()], max_steps=2, conversation_id="shared")
    agent_b.run("keep-b", [_RecordingTool()], max_steps=2, conversation_id="shared")

    ClearAgentThread(
        LangGraphThreadMemory(checkpointer=saver, workspace_id="ws-b")
    ).execute(conversation_id="shared")
    ClearAgentThread(
        LangGraphThreadMemory(checkpointer=saver, workspace_id="ws-b")
    ).execute(conversation_id="shared")

    chat_after = _ScriptedChat([_ai_text("again-a")])
    LangGraphToolAgent(
        system_prompt=_SYSTEM,
        model_factory=_RecordingFactory(chat_after),
        checkpointer=saver,
        workspace_id="ws-a",
    ).run("follow-a", [_RecordingTool()], max_steps=2, conversation_id="shared")

    follow = chat_after.invoke_messages[0]
    assert any(isinstance(m, HumanMessage) and m.content == "keep-a" for m in follow)
