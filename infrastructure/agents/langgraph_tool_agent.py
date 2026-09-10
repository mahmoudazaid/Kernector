"""LangGraph adapter for the ``ToolCallingAgent`` port."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Protocol, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from domain.errors import ProviderError, ToolArgumentValidationError, ToolFailureError
from domain.models import AgentTurnResult
from domain.ports import Tool

_CONNECTION_FAILURE_MESSAGE = "The tool-calling agent provider could not be reached."
_EMPTY_FINAL_MESSAGE = "The agent finished without a final answer."
_SYSTEM_PROMPT = (
    "You are a tool-calling agent. Use the bound tools when needed, "
    "then answer the goal with a concise final message."
)


class _ChatModelLike(Protocol):
    def bind_tools(self, tools: Sequence[object]) -> Any: ...

    def invoke(self, messages: Sequence[BaseMessage], **kwargs: object) -> Any: ...


class _ModelFactory(Protocol):
    def __call__(self, **kwargs: object) -> _ChatModelLike: ...


class _AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    steps: int


def _default_model_factory(**_kwargs: object) -> _ChatModelLike:
    raise ProviderError(_CONNECTION_FAILURE_MESSAGE)


class LangGraphToolAgent:
    """Minimal ReAct-style ``StateGraph`` behind ``ToolCallingAgent``.

    Args:
        model_factory (_ModelFactory | None): Injectable factory that returns a
            chat model supporting ``bind_tools`` and ``invoke``. Tests inject a
            scripted fake; production supplies a live factory.
    """

    def __init__(self, *, model_factory: _ModelFactory | None = None) -> None:
        self._model_factory = model_factory or _default_model_factory

    def run(
        self,
        goal: str,
        tools: Sequence[Tool],
        *,
        max_steps: int,
    ) -> AgentTurnResult:
        """Run a model ↔ tools loop for ``goal`` with a hard ``max_steps`` stop.

        Raises:
            ProviderError: Model or graph runtime failure (fixed message).
            ToolArgumentValidationError: Propagated from a bound tool.
            ToolFailureError: Propagated from a bound tool.
        """
        lc_tools = [_to_langchain_tool(tool) for tool in tools]
        tools_by_name = {tool.name: tool for tool in tools}
        model = self._model_factory().bind_tools(lc_tools)

        def call_model(state: _AgentState) -> Mapping[str, object]:
            steps = int(state.get("steps", 0)) + 1
            if steps > max_steps:
                return {
                    "messages": [AIMessage(content=_EMPTY_FINAL_MESSAGE)],
                    "steps": steps,
                }
            try:
                response = model.invoke(state["messages"])
            except Exception as exc:
                raise ProviderError(_CONNECTION_FAILURE_MESSAGE) from exc
            return {"messages": [response], "steps": steps}

        def call_tools(state: _AgentState) -> Mapping[str, object]:
            last = state["messages"][-1]
            tool_calls = getattr(last, "tool_calls", None) or ()
            outputs: list[ToolMessage] = []
            for call in tool_calls:
                name = call["name"]
                args = call.get("args") or {}
                tool = tools_by_name[name]
                result = tool.run(args if isinstance(args, Mapping) else {})
                outputs.append(
                    ToolMessage(
                        content=result,
                        name=name,
                        tool_call_id=call["id"],
                    )
                )
            return {"messages": outputs}

        def should_continue(state: _AgentState) -> str:
            last = state["messages"][-1]
            tool_calls = getattr(last, "tool_calls", None) or ()
            # Always execute pending tool calls; max_steps caps further model turns.
            return "tools" if tool_calls else "end"

        graph = StateGraph(_AgentState)
        graph.add_node("agent", call_model)
        graph.add_node("tools", call_tools)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges(
            "agent",
            should_continue,
            {"tools": "tools", "end": END},
        )
        graph.add_edge("tools", "agent")
        compiled = graph.compile()

        try:
            final_state = compiled.invoke(
                {
                    "messages": [
                        SystemMessage(content=_SYSTEM_PROMPT),
                        HumanMessage(content=goal),
                    ],
                    "steps": 0,
                }
            )
        except (ToolArgumentValidationError, ToolFailureError):
            raise
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(_CONNECTION_FAILURE_MESSAGE) from exc

        content = _final_text(final_state["messages"])
        steps = int(final_state.get("steps", 0))
        return AgentTurnResult(content=content, steps=steps)


def _to_langchain_tool(tool: Tool) -> StructuredTool:
    """Wrap a domain ``Tool`` as a LangChain structured tool (infra only)."""

    def _run(**kwargs: object) -> str:
        return tool.run(kwargs)

    return StructuredTool.from_function(
        func=_run,
        name=tool.name,
        description=tool.description,
    )


def _final_text(messages: Sequence[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            tool_calls = getattr(message, "tool_calls", None) or ()
            if tool_calls:
                continue
            content = message.content
            if isinstance(content, str) and content.strip():
                return content
    raise ProviderError(_CONNECTION_FAILURE_MESSAGE) from ValueError(
        _EMPTY_FINAL_MESSAGE
    )
