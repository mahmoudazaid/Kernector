"""LangGraph tool-calling agent, tested through an injected model factory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from domain.errors import ProviderError
from domain.models import AgentTurnResult


class _RecordingTool:
    """Domain ``Tool`` double that records each invocation."""

    def __init__(self, name: str = "lookup", result: str = "lookup-ok") -> None:
        self._name = name
        self._result = result
        self.calls: list[Mapping[str, object]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Tool {self._name}"

    def run(self, arguments: Mapping[str, object]) -> str:
        self.calls.append(dict(arguments))
        return self._result


class _ScriptedChat:
    """Fake chat model: returns queued messages; optional bind_tools."""

    def __init__(self, messages: Sequence[object], *, error: Exception | None = None) -> None:
        self._messages = list(messages)
        self._error = error
        self.bound_tools: list[object] | None = None
        self.invocations = 0

    def bind_tools(self, tools: Sequence[object]) -> _ScriptedChat:
        self.bound_tools = list(tools)
        return self

    def invoke(self, _messages: object, **_kwargs: object) -> object:
        self.invocations += 1
        if self._error is not None:
            raise self._error
        if not self._messages:
            raise AssertionError("scripted chat exhausted")
        return self._messages.pop(0)


class _RecordingFactory:
    def __init__(self, chat: _ScriptedChat) -> None:
        self._chat = chat
        self.calls = 0

    def __call__(self, **_kwargs: object) -> _ScriptedChat:
        self.calls += 1
        return self._chat


def _ai_tool_call(*, name: str, call_id: object = "call_1", args: Mapping[str, object] | None = None):
    from langchain_core.messages import AIMessage

    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": dict(args or {}), "id": call_id}],
    )


def _ai_text(content: object):
    from langchain_core.messages import AIMessage

    return AIMessage(content=content)


def test_langgraph_tool_agent_invokes_tool_then_stops_on_final_message() -> None:
    from infrastructure.agents.langgraph_tool_agent import LangGraphToolAgent

    tool = _RecordingTool()
    chat = _ScriptedChat([_ai_tool_call(name=tool.name), _ai_text("Done with lookup.")])
    agent = LangGraphToolAgent(model_factory=_RecordingFactory(chat))

    result = agent.run("Look up the value", [tool], max_steps=5)

    assert result == AgentTurnResult(content="Done with lookup.", steps=2)
    assert tool.calls == [{}]
    assert chat.invocations == 2
    assert chat.bound_tools is not None


def test_langgraph_tool_agent_maps_model_failure_to_provider_error() -> None:
    from infrastructure.agents.langgraph_tool_agent import LangGraphToolAgent

    chat = _ScriptedChat([], error=RuntimeError("vendor secret TOKEN=xyz"))
    agent = LangGraphToolAgent(model_factory=_RecordingFactory(chat))

    with pytest.raises(ProviderError, match="could not be reached") as caught:
        agent.run("goal", [_RecordingTool()], max_steps=3)

    assert "TOKEN=xyz" not in str(caught.value)
    assert caught.value.__cause__ is not None
    assert "TOKEN=xyz" in str(caught.value.__cause__)


def test_langgraph_tool_agent_accepts_list_shaped_final_content() -> None:
    from infrastructure.agents.langgraph_tool_agent import LangGraphToolAgent

    chat = _ScriptedChat(
        [_ai_text([{"type": "text", "text": "final answer here"}])]
    )
    agent = LangGraphToolAgent(model_factory=_RecordingFactory(chat))

    result = agent.run("goal", [_RecordingTool()], max_steps=3)

    assert result.content == "final answer here"


def test_langgraph_tool_agent_raises_on_step_limit() -> None:
    from infrastructure.agents.langgraph_tool_agent import LangGraphToolAgent

    tool = _RecordingTool()
    # Every model turn requests the tool again so the cap is hit after tools run.
    chat = _ScriptedChat(
        [
            _ai_tool_call(name=tool.name, call_id="1"),
            _ai_tool_call(name=tool.name, call_id="2"),
            _ai_tool_call(name=tool.name, call_id="3"),
            _ai_tool_call(name=tool.name, call_id="4"),
        ]
    )
    agent = LangGraphToolAgent(model_factory=_RecordingFactory(chat))

    with pytest.raises(ProviderError, match="step limit"):
        agent.run("goal", [tool], max_steps=3)


def test_langgraph_tool_agent_unknown_tool_returns_tool_message() -> None:
    from infrastructure.agents.langgraph_tool_agent import LangGraphToolAgent

    tool = _RecordingTool()
    chat = _ScriptedChat(
        [
            _ai_tool_call(name="nope", call_id="bad"),
            _ai_text("Recovered after unknown tool."),
        ]
    )
    agent = LangGraphToolAgent(model_factory=_RecordingFactory(chat))

    result = agent.run("goal", [tool], max_steps=4)

    assert result.content == "Recovered after unknown tool."
    assert tool.calls == []


def test_langgraph_tool_agent_synthesises_missing_tool_call_id() -> None:
    from infrastructure.agents.langgraph_tool_agent import LangGraphToolAgent

    tool = _RecordingTool()
    chat = _ScriptedChat(
        [
            _ai_tool_call(name=tool.name, call_id=None),
            _ai_text("ok"),
        ]
    )
    agent = LangGraphToolAgent(model_factory=_RecordingFactory(chat))

    result = agent.run("goal", [tool], max_steps=3)

    assert result.content == "ok"
    assert tool.calls == [{}]


def test_langgraph_tool_agent_sanitises_dotted_tool_names_for_binding() -> None:
    from infrastructure.agents.langgraph_tool_agent import (
        LangGraphToolAgent,
        _bind_tool_name,
    )

    tool = _RecordingTool(name="software_delivery.risk_score")
    bind_name = _bind_tool_name(tool.name)
    chat = _ScriptedChat(
        [
            _ai_tool_call(name=bind_name),
            _ai_text("scored"),
        ]
    )
    agent = LangGraphToolAgent(model_factory=_RecordingFactory(chat))

    result = agent.run("goal", [tool], max_steps=3)

    assert result.content == "scored"
    assert tool.calls == [{}]
    assert chat.bound_tools is not None
    assert chat.bound_tools[0].name == bind_name
    assert "." not in chat.bound_tools[0].name


def test_langgraph_tool_agent_binds_empty_args_schema() -> None:
    from infrastructure.agents.langgraph_tool_agent import LangGraphToolAgent

    tool = _RecordingTool()
    chat = _ScriptedChat([_ai_text("done")])
    agent = LangGraphToolAgent(model_factory=_RecordingFactory(chat))

    agent.run("goal", [tool], max_steps=2)

    schema = chat.bound_tools[0].args_schema.model_json_schema()  # type: ignore[union-attr]
    assert schema.get("properties", {}) == {}
