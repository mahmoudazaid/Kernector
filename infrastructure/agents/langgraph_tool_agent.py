"""LangGraph adapter for the ``ToolCallingAgent`` port."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, NoReturn, Protocol, TypedDict
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

from domain.errors import (
    ConfigurationBoundaryError,
    ProviderError,
    ToolArgumentValidationError,
    ToolFailureError,
)
from domain.models import AgentTurnResult
from domain.ports import Tool

_CONNECTION_FAILURE_MESSAGE = "The tool-calling agent provider could not be reached."
_STEP_LIMIT_CONTENT = "Stopped after reaching the step limit."
_EMPTY_FINAL_MESSAGE = "The agent finished without a final answer."
_INVALID_TOOL_ARGS_MESSAGE = "Tool call arguments could not be parsed."


def _provider_or_reraise(exc: BaseException) -> NoReturn:
    """Re-raise config/ValueError as-is; otherwise raise connectivity ProviderError."""
    if isinstance(exc, (ProviderError, ConfigurationBoundaryError, ValueError)):
        raise exc
    raise ProviderError(_CONNECTION_FAILURE_MESSAGE) from exc


class _ChatModelLike(Protocol):
    def bind_tools(self, tools: Sequence[object], *args: object, **kwargs: object) -> Any: ...

    def invoke(self, messages: Sequence[BaseMessage], **kwargs: object) -> Any: ...


class _ModelFactory(Protocol):
    def __call__(self, **kwargs: object) -> _ChatModelLike: ...


class _AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    steps: int
    truncated: bool


class _EmptyToolArgs(BaseModel):
    """No parameters — domain tools receive closed-over arguments."""

    model_config = ConfigDict(extra="forbid")


def _default_model_factory(**_kwargs: object) -> _ChatModelLike:
    raise ProviderError(_CONNECTION_FAILURE_MESSAGE)


def _bind_tool_name(name: str) -> str:
    """Map pack tool names to OpenAI-compatible function names (no ``.``)."""
    return name.replace(".", "__")


class LangGraphToolAgent:
    """Minimal ReAct-style ``StateGraph`` behind ``ToolCallingAgent``.

    The graph is compiled per ``run`` with closures over that turn's model and
    tools. ``system_prompt`` is required so callers always supply trust-marker
    wording (owned by application/composition).

    Args:
        model_factory (_ModelFactory | None): Injectable chat-model factory.
        system_prompt (str): System message for the agent turn.
    """

    def __init__(
        self,
        *,
        system_prompt: str,
        model_factory: _ModelFactory | None = None,
    ) -> None:
        self._model_factory = model_factory or _default_model_factory
        self._system_prompt = system_prompt

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
            ConfigurationBoundaryError: Propagated typed config failure from the
                model factory (application ``ConfigurationError`` subclasses).
            ValueError: Propagated when the factory rejects an unknown provider.
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
            _provider_or_reraise(exc)

        def call_model(state: _AgentState) -> Mapping[str, object]:
            steps = int(state.get("steps", 0)) + 1
            if steps > max_steps:
                return {
                    "messages": [AIMessage(content=_STEP_LIMIT_CONTENT)],
                    # Do not count the refused step as completed work.
                    "steps": steps - 1,
                    "truncated": True,
                }
            try:
                response = model.invoke(state["messages"])
            except ProviderError:
                raise
            except Exception as exc:
                _provider_or_reraise(exc)
            response = _with_normalised_tool_calls(response)
            return {"messages": [response], "steps": steps, "truncated": False}

        def call_tools(state: _AgentState) -> Mapping[str, object]:
            last = state["messages"][-1]
            tool_calls = getattr(last, "tool_calls", None) or ()
            outputs: list[ToolMessage] = []
            for index, call in enumerate(tool_calls):
                if not isinstance(call, Mapping):
                    call_id = _tool_call_id({}, index)
                    outputs.append(
                        ToolMessage(
                            content="Tool call was malformed.",
                            name="unknown",
                            tool_call_id=call_id,
                        )
                    )
                    continue
                bind_name = call.get("name")
                if not isinstance(bind_name, str) or not bind_name.strip():
                    bind_name = "unknown"
                call_id = _tool_call_id(call, index)
                if call.get("error"):
                    outputs.append(
                        ToolMessage(
                            content=_INVALID_TOOL_ARGS_MESSAGE,
                            name=bind_name,
                            tool_call_id=call_id,
                        )
                    )
                    continue
                args = call.get("args") or {}
                # Normalisation always leaves Mapping args (or sets error above).
                assert isinstance(args, Mapping)
                tool = tools_by_bind_name.get(bind_name)
                if tool is None:
                    available = ", ".join(sorted(tools_by_bind_name))
                    outputs.append(
                        ToolMessage(
                            content=(
                                "Unknown tool name. "
                                f"Available tools: {available or '(none)'}."
                            ),
                            name=bind_name,
                            tool_call_id=call_id,
                        )
                    )
                    continue
                result = tool.run(args)
                outputs.append(
                    ToolMessage(
                        content=result,
                        name=bind_name,
                        tool_call_id=call_id,
                    )
                )
            return {"messages": outputs}

        def should_continue(state: _AgentState) -> str:
            if state.get("truncated"):
                return "end"
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
        compiled = graph.compile()

        try:
            final_state = compiled.invoke(
                {
                    "messages": [
                        SystemMessage(content=self._system_prompt),
                        HumanMessage(content=goal),
                    ],
                    "steps": 0,
                    "truncated": False,
                }
            )
        except (ToolArgumentValidationError, ToolFailureError):
            raise
        except ProviderError:
            raise
        except Exception as exc:
            _provider_or_reraise(exc)

        truncated = bool(final_state.get("truncated"))
        steps = int(final_state.get("steps", 0))
        if truncated:
            return AgentTurnResult(
                content=_STEP_LIMIT_CONTENT, steps=steps, truncated=True
            )
        content = _final_text(final_state["messages"])
        if content is None:
            # Soft stop so callers keep completed tool outcomes; not a step-limit.
            return AgentTurnResult(
                content=_EMPTY_FINAL_MESSAGE, steps=steps, truncated=False
            )
        return AgentTurnResult(content=content, steps=steps, truncated=False)


def _with_normalised_tool_calls(message: object) -> object:
    """Ensure assistant tool_calls are serialisable; fold invalid_tool_calls in.

    LangChain routes unparseable tool arguments into ``invalid_tool_calls``, but
    the OpenAI wire format still echoes those ids on the next turn. Fold them
    into ``tool_calls`` (and clear ``invalid_tool_calls``) so ``call_tools``
    always emits a matching ``ToolMessage``.
    """
    if not isinstance(message, AIMessage):
        return message
    tool_calls = list(getattr(message, "tool_calls", None) or ())
    invalid_calls = list(getattr(message, "invalid_tool_calls", None) or ())
    if not tool_calls and not invalid_calls:
        return message

    normalised: list[dict[str, object]] = []
    changed = bool(invalid_calls)
    for index, call in enumerate(tool_calls):
        if not isinstance(call, Mapping):
            normalised.append(
                {
                    "name": "unknown",
                    "args": {},
                    "id": _tool_call_id({}, index),
                    "error": _INVALID_TOOL_ARGS_MESSAGE,
                }
            )
            changed = True
            continue
        call_dict = dict(call)
        name = call_dict.get("name")
        if not isinstance(name, str) or not name.strip():
            call_dict["name"] = "unknown"
            changed = True
        if "args" not in call_dict or call_dict["args"] is None:
            call_dict["args"] = {}
            changed = True
        elif not isinstance(call_dict["args"], Mapping):
            call_dict["args"] = {}
            call_dict["error"] = (
                call_dict.get("error") or _INVALID_TOOL_ARGS_MESSAGE
            )
            changed = True
        new_id = _tool_call_id(call_dict, index)
        if call_dict.get("id") != new_id:
            call_dict["id"] = new_id
            changed = True
        normalised.append(call_dict)

    base_index = len(normalised)
    for offset, call in enumerate(invalid_calls):
        index = base_index + offset
        if isinstance(call, Mapping):
            raw_name = call.get("name")
            name = (
                raw_name.strip()
                if isinstance(raw_name, str) and raw_name.strip()
                else "unknown"
            )
            call_id = _tool_call_id(call, index)
            error = call.get("error")
            if not isinstance(error, str) or not error.strip():
                error = _INVALID_TOOL_ARGS_MESSAGE
            # Preserve id/name so call_tools can reply; args stay empty.
            normalised.append(
                {
                    "name": name,
                    "args": {},
                    "id": call_id,
                    "type": "tool_call",
                    "error": error,
                }
            )
        else:
            normalised.append(
                {
                    "name": "unknown",
                    "args": {},
                    "id": _tool_call_id({}, index),
                    "type": "tool_call",
                    "error": _INVALID_TOOL_ARGS_MESSAGE,
                }
            )

    if not changed:
        return message
    return message.model_copy(
        update={"tool_calls": normalised, "invalid_tool_calls": []}
    )


def _tool_call_id(call: Mapping[str, object], index: int) -> str:
    raw = call.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw
    return f"call_{index}_{uuid4().hex[:8]}"


def _to_langchain_tool(tool: Tool) -> StructuredTool:
    """Advertise a domain tool for ``bind_tools`` without a callable schema."""

    def _unused() -> str:
        return ""

    return StructuredTool.from_function(
        func=_unused,
        name=_bind_tool_name(tool.name),
        description=tool.description,
        args_schema=_EmptyToolArgs,
    )


def _final_text(messages: Sequence[BaseMessage]) -> str | None:
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        tool_calls = getattr(message, "tool_calls", None) or ()
        if tool_calls:
            continue
        text = getattr(message, "text", None)
        if text is None:
            continue
        normalised = str(text).strip()
        if normalised:
            return normalised
    return None
