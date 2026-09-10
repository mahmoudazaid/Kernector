"""LangGraph adapter for the ``ToolCallingAgent`` port."""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Protocol, TypedDict
from uuid import uuid4

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
from pydantic import BaseModel, ConfigDict

from domain.errors import ProviderError, ToolArgumentValidationError, ToolFailureError
from domain.models import AgentTurnResult
from domain.ports import Tool

_CONNECTION_FAILURE_MESSAGE = "The tool-calling agent provider could not be reached."
_STEP_LIMIT_MESSAGE = "The agent exceeded its step limit."
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


class _EmptyToolArgs(BaseModel):
    """No parameters — domain tools receive closed-over arguments."""

    model_config = ConfigDict(extra="forbid")


@dataclass(slots=True)
class _RunContext:
    model: Any
    tools_by_bind_name: dict[str, Tool]
    max_steps: int


def _default_model_factory(**_kwargs: object) -> _ChatModelLike:
    raise ProviderError(_CONNECTION_FAILURE_MESSAGE)


def _bind_tool_name(name: str) -> str:
    """Map pack tool names to OpenAI-compatible function names (no ``.``)."""
    return name.replace(".", "__")


class LangGraphToolAgent:
    """Minimal ReAct-style ``StateGraph`` behind ``ToolCallingAgent``.

    The compiled graph is built once; per-run model/tools/max_steps live on a
    thread-local context so concurrent turns do not share closures.

    Args:
        model_factory (_ModelFactory | None): Injectable factory that returns a
            chat model supporting ``bind_tools`` and ``invoke``. Tests inject a
            scripted fake; production supplies a live factory.
    """

    def __init__(self, *, model_factory: _ModelFactory | None = None) -> None:
        self._model_factory = model_factory or _default_model_factory
        self._tls = threading.local()
        self._graph = self._compile_graph()

    def run(
        self,
        goal: str,
        tools: Sequence[Tool],
        *,
        max_steps: int,
    ) -> AgentTurnResult:
        """Run a model ↔ tools loop for ``goal`` with a hard ``max_steps`` stop.

        Raises:
            ProviderError: Model/runtime failure or step-limit exhaustion.
            ToolArgumentValidationError: Propagated from a bound tool.
            ToolFailureError: Propagated from a bound tool.
        """
        lc_tools = [_to_langchain_tool(tool) for tool in tools]
        tools_by_bind_name = {_bind_tool_name(tool.name): tool for tool in tools}
        try:
            model = self._model_factory().bind_tools(lc_tools)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(_CONNECTION_FAILURE_MESSAGE) from exc

        self._tls.ctx = _RunContext(
            model=model,
            tools_by_bind_name=tools_by_bind_name,
            max_steps=max_steps,
        )
        try:
            try:
                final_state = self._graph.invoke(
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
        finally:
            self._tls.ctx = None

    def _compile_graph(self) -> Any:
        def call_model(state: _AgentState) -> Mapping[str, object]:
            ctx: _RunContext = self._tls.ctx
            steps = int(state.get("steps", 0)) + 1
            if steps > ctx.max_steps:
                raise ProviderError(_STEP_LIMIT_MESSAGE)
            try:
                response = ctx.model.invoke(state["messages"])
            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError(_CONNECTION_FAILURE_MESSAGE) from exc
            return {"messages": [response], "steps": steps}

        def call_tools(state: _AgentState) -> Mapping[str, object]:
            ctx: _RunContext = self._tls.ctx
            last = state["messages"][-1]
            tool_calls = getattr(last, "tool_calls", None) or ()
            outputs: list[ToolMessage] = []
            for index, call in enumerate(tool_calls):
                bind_name = call["name"]
                args = call.get("args") or {}
                call_id = _tool_call_id(call, index)
                tool = ctx.tools_by_bind_name.get(bind_name)
                if tool is None:
                    available = ", ".join(sorted(ctx.tools_by_bind_name))
                    outputs.append(
                        ToolMessage(
                            content=(
                                f"Unknown tool {bind_name!r}. "
                                f"Available tools: {available or '(none)'}."
                            ),
                            name=bind_name,
                            tool_call_id=call_id,
                        )
                    )
                    continue
                result = tool.run(args if isinstance(args, Mapping) else {})
                outputs.append(
                    ToolMessage(
                        content=result,
                        name=bind_name,
                        tool_call_id=call_id,
                    )
                )
            return {"messages": outputs}

        def should_continue(state: _AgentState) -> str:
            last = state["messages"][-1]
            tool_calls = getattr(last, "tool_calls", None) or ()
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
        return graph.compile()


def _tool_call_id(call: Mapping[str, object], index: int) -> str:
    raw = call.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw
    return f"call_{index}_{uuid4().hex[:8]}"


def _to_langchain_tool(tool: Tool) -> StructuredTool:
    """Advertise a domain tool for ``bind_tools`` without a callable schema.

    ``call_tools`` invokes the domain ``Tool`` directly; the StructuredTool
    exists only so the model sees name/description and an empty parameter list.
    """

    def _unused() -> str:
        return ""

    return StructuredTool.from_function(
        func=_unused,
        name=_bind_tool_name(tool.name),
        description=tool.description,
        args_schema=_EmptyToolArgs,
    )


def _final_text(messages: Sequence[BaseMessage]) -> str:
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        tool_calls = getattr(message, "tool_calls", None) or ()
        if tool_calls:
            continue
        text = getattr(message, "text", None)
        if isinstance(text, str) and text.strip():
            return text
        normalized = _normalize_content(message.content)
        if normalized:
            return normalized
    raise ProviderError(_CONNECTION_FAILURE_MESSAGE) from ValueError(
        _EMPTY_FINAL_MESSAGE
    )


def _normalize_content(content: object) -> str | None:
    if isinstance(content, str) and content.strip():
        return content
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if isinstance(block, Mapping) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    joined = "".join(parts).strip()
    return joined or None
