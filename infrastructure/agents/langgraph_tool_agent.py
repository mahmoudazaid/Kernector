"""LangGraph adapter for the ``ToolCallingAgent`` port.

Short-term thread memory uses an injected LangGraph ``InMemorySaver`` when
``workspace_id`` and ``conversation_id`` are set. Checkpoints are
**process-local**: a process restart drops all threads. Suitable for
testing/debugging; durable stores are deferred (#299).

#214: when a ``ToolApprovalPolicy`` is injected, ``interrupt()`` runs
immediately before ``Tool.run`` for allowlisted tools. Pending approvals and
replay protection are process-local with the checkpointer.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
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
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from pydantic import BaseModel, ConfigDict

from domain.errors import ToolApprovalNotFoundError
from domain.tool_approval import (
    ApprovalHints,
    Decision,
    ToolApprovalPolicy,
    project_pending_approval,
)
from domain.errors import (
    ConfigurationBoundaryError,
    ProviderError,
    ToolArgumentValidationError,
    ToolFailureError,
)
from domain.models import AgentTurnResult
from domain.ports import Tool
from domain.thread_memory import scoped_thread_key
from domain.tool_approval import PendingToolApproval

_CONNECTION_FAILURE_MESSAGE = "The tool-calling agent provider could not be reached."
_STEP_LIMIT_CONTENT = "Stopped after reaching the step limit."
_EMPTY_FINAL_MESSAGE = "The agent finished without a final answer."
_INVALID_TOOL_ARGS_MESSAGE = "Tool call arguments could not be parsed."
_PENDING_APPROVAL_CONTENT = "Waiting for approval before continuing."
_CANCELLED_TOOL_CONTENT = "Export cancelled."
STABLE_SYSTEM_MESSAGE_ID = "kernector-agent-system"


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


class LangGraphThreadMemory:
    """``AgentThreadMemory`` adapter over a shared ``InMemorySaver``."""

    def __init__(
        self,
        *,
        checkpointer: InMemorySaver,
        workspace_id: str,
    ) -> None:
        self._checkpointer = checkpointer
        self._workspace_id = workspace_id

    def clear(self, *, conversation_id: str) -> None:
        """Drop short-term checkpoints for ``conversation_id`` (idempotent)."""
        thread_id = scoped_thread_key(self._workspace_id, conversation_id)
        self._checkpointer.delete_thread(thread_id)


class LangGraphToolAgent:
    """Minimal ReAct-style ``StateGraph`` behind ``ToolCallingAgent``."""

    def __init__(
        self,
        *,
        system_prompt: str,
        model_factory: _ModelFactory | None = None,
        checkpointer: InMemorySaver | None = None,
        workspace_id: str | None = None,
        approval_policy: ToolApprovalPolicy | None = None,
        pending_args: MutableMapping[str, Mapping[str, object]] | None = None,
        approval_hints: MutableMapping[str, ApprovalHints] | None = None,
        tools_by_conversation: MutableMapping[str, dict[str, Tool]] | None = None,
        approval_results: MutableMapping[str, str] | None = None,
        approvals_by_conversation: MutableMapping[str, set[str]] | None = None,
    ) -> None:
        self._model_factory = model_factory or _default_model_factory
        self._system_prompt = system_prompt
        self._checkpointer = checkpointer
        self._workspace_id = workspace_id
        self._approval_policy = approval_policy or ToolApprovalPolicy(frozenset())
        self._pending_args: MutableMapping[str, Mapping[str, object]] = (
            pending_args if pending_args is not None else {}
        )
        self._approval_hints: MutableMapping[str, ApprovalHints] = (
            approval_hints if approval_hints is not None else {}
        )
        self._tools_by_conversation: MutableMapping[str, dict[str, Tool]] = (
            tools_by_conversation if tools_by_conversation is not None else {}
        )
        self._approval_results: MutableMapping[str, str] = (
            approval_results if approval_results is not None else {}
        )
        self._approvals_by_conversation: MutableMapping[str, set[str]] = (
            approvals_by_conversation
            if approvals_by_conversation is not None
            else {}
        )

    def run(
        self,
        goal: str,
        tools: Sequence[Tool],
        *,
        max_steps: int,
        conversation_id: str | None = None,
    ) -> AgentTurnResult:
        """Run a model ↔ tools loop for ``goal`` with a hard ``max_steps`` stop."""
        tools_by_name = {tool.name: tool for tool in tools}
        for tool in tools:
            hints = getattr(tool, "approval_hints", None)
            if isinstance(hints, ApprovalHints):
                self._approval_hints[tool.name] = hints
        conversation_key = (
            conversation_id.strip()
            if isinstance(conversation_id, str) and conversation_id.strip()
            else None
        )
        if conversation_key is not None:
            self._tools_by_conversation[conversation_key] = tools_by_name

        compiled, use_memory = self._compile(
            tools, max_steps=max_steps, conversation_id=conversation_key
        )
        input_state: Mapping[str, object] = {
            "messages": [
                SystemMessage(
                    content=self._system_prompt,
                    id=STABLE_SYSTEM_MESSAGE_ID,
                ),
                HumanMessage(content=goal),
            ],
            "steps": 0,
            "truncated": False,
        }

        try:
            if use_memory:
                assert self._workspace_id is not None
                assert conversation_key is not None
                thread_id = scoped_thread_key(self._workspace_id, conversation_key)
                final_state = compiled.invoke(
                    input_state,
                    {"configurable": {"thread_id": thread_id}},
                )
            else:
                final_state = compiled.invoke(input_state)
        except (ToolArgumentValidationError, ToolFailureError):
            raise
        except ProviderError:
            raise
        except Exception as exc:
            _provider_or_reraise(exc)

        return self._result_from_state(final_state)

    def resume_approval(
        self,
        *,
        conversation_id: str,
        approval_id: str,
        decision: Decision,
    ) -> AgentTurnResult:
        """Resume an interrupted thread with approve|reject for ``approval_id``."""
        if self._checkpointer is None or self._workspace_id is None:
            raise ToolApprovalNotFoundError("No pending approval for this conversation.")
        if not conversation_id.strip():
            raise ToolApprovalNotFoundError("No pending approval for this conversation.")
        conversation_key = conversation_id.strip()
        thread_id = scoped_thread_key(self._workspace_id, conversation_key)
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = self._checkpointer.get_tuple(config)
        if snapshot is None:
            raise ToolApprovalNotFoundError("No pending approval for this conversation.")

        interrupts = tuple(getattr(snapshot, "interrupts", ()) or ())
        matched = False
        for item in interrupts:
            value = getattr(item, "value", None)
            if isinstance(value, Mapping) and value.get("approval_id") == approval_id:
                matched = True
                break
        if interrupts and not matched:
            raise ToolApprovalNotFoundError("No pending approval for this conversation.")
        owned = self._approvals_by_conversation.get(conversation_key) or set()
        if approval_id in self._pending_args and approval_id not in owned:
            raise ToolApprovalNotFoundError("No pending approval for this conversation.")
        if not interrupts and approval_id not in self._pending_args:
            values = snapshot.checkpoint.get("channel_values", {})
            return self._result_from_state(values)

        tools_by_name = self._tools_by_conversation.get(conversation_key) or {}
        tools = list(tools_by_name.values())
        compiled, _ = self._compile(
            tools, max_steps=32, conversation_id=conversation_key
        )
        try:
            final_state = compiled.invoke(
                Command(resume={"decision": decision, "approval_id": approval_id}),
                config,
            )
        except (ToolArgumentValidationError, ToolFailureError):
            raise
        except ProviderError:
            raise
        except Exception as exc:
            _provider_or_reraise(exc)
        return self._result_from_state(final_state)

    def _compile(
        self,
        tools: Sequence[Tool],
        *,
        max_steps: int,
        conversation_id: str | None,
    ):
        lc_tools = [_to_langchain_tool(tool) for tool in tools]
        tools_by_bind_name = {_bind_tool_name(tool.name): tool for tool in tools}
        try:
            model = self._model_factory().bind_tools(lc_tools)
        except ProviderError:
            raise
        except Exception as exc:
            _provider_or_reraise(exc)

        policy = self._approval_policy
        pending_args = self._pending_args
        hints_by_name = self._approval_hints
        approval_results = self._approval_results
        approvals_by_conversation = self._approvals_by_conversation
        conversation_key = (
            conversation_id.strip()
            if isinstance(conversation_id, str) and conversation_id.strip()
            else None
        )

        def call_model(state: _AgentState) -> Mapping[str, object]:
            steps = int(state.get("steps", 0)) + 1
            if steps > max_steps:
                return {
                    "messages": [AIMessage(content=_STEP_LIMIT_CONTENT)],
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
                if policy.requires_approval(tool.name):
                    # Stable across resume re-entry (LangGraph re-runs pre-interrupt).
                    approval_id = call_id
                    # Prefer closed-over BoundTool args (LLM args are often empty).
                    bound_args = getattr(tool, "_arguments", None)
                    projection_args: Mapping[str, object] = (
                        bound_args
                        if isinstance(bound_args, Mapping) and bound_args
                        else args
                    )
                    if approval_id not in pending_args:
                        pending_args[approval_id] = dict(projection_args)
                    if conversation_key is not None:
                        approvals_by_conversation.setdefault(
                            conversation_key, set()
                        ).add(approval_id)
                    pending = project_pending_approval(
                        approval_id=approval_id,
                        tool_name=tool.name,
                        arguments=projection_args,
                        hints=hints_by_name.get(tool.name),
                    )
                    decision = interrupt(
                        {
                            "approval_id": pending.approval_id,
                            "tool_name": pending.tool_name,
                            "title": pending.title,
                            "summary": pending.summary,
                            "status": "pending",
                            "destination_label": pending.destination_label,
                            "file_name": pending.file_name,
                            "selected_title_count": pending.selected_title_count,
                        }
                    )
                    decision_name = _decision_from_resume(decision, approval_id)
                    if decision_name == "reject":
                        pending_args.pop(approval_id, None)
                        approval_results.pop(approval_id, None)
                        outputs.append(
                            ToolMessage(
                                content=_CANCELLED_TOOL_CONTENT,
                                name=bind_name,
                                tool_call_id=call_id,
                            )
                        )
                        continue
                    stored = pending_args.pop(approval_id, dict(args))
                    result = tool.run(stored)
                    approval_results[approval_id] = result
                else:
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

        use_memory = (
            self._checkpointer is not None
            and self._workspace_id is not None
            and conversation_id is not None
            and str(conversation_id).strip() != ""
        )
        compiled = (
            graph.compile(checkpointer=self._checkpointer)
            if use_memory
            else graph.compile()
        )
        return compiled, use_memory

    def take_approval_result(self, approval_id: str) -> str | None:
        """Return and clear a post-approve tool result string, if any."""
        return self._approval_results.pop(approval_id, None)

    def _result_from_state(self, final_state: Mapping[str, object]) -> AgentTurnResult:
        interrupts = final_state.get("__interrupt__")
        if interrupts:
            pending = _pending_from_interrupts(interrupts)
            if pending is not None:
                return AgentTurnResult(
                    content=_PENDING_APPROVAL_CONTENT,
                    steps=int(final_state.get("steps", 0) or 0),
                    truncated=False,
                    pending_approval=pending,
                )
        truncated = bool(final_state.get("truncated"))
        steps = int(final_state.get("steps", 0) or 0)
        if truncated:
            return AgentTurnResult(
                content=_STEP_LIMIT_CONTENT, steps=steps, truncated=True
            )
        messages = final_state.get("messages") or ()
        content = _final_text(messages)
        if content is None:
            return AgentTurnResult(
                content=_EMPTY_FINAL_MESSAGE, steps=steps, truncated=False
            )
        return AgentTurnResult(content=content, steps=steps, truncated=False)


def _decision_from_resume(decision: object, approval_id: str) -> Decision:
    if isinstance(decision, Mapping):
        if decision.get("approval_id") not in (None, approval_id):
            return "reject"
        raw = decision.get("decision")
        if raw == "approve":
            return "approve"
        return "reject"
    if decision == "approve":
        return "approve"
    return "reject"


def _pending_from_interrupts(interrupts: object) -> PendingToolApproval | None:
    if not isinstance(interrupts, Sequence):
        return None
    for item in interrupts:
        value = getattr(item, "value", item)
        if not isinstance(value, Mapping):
            continue
        try:
            return PendingToolApproval(
                approval_id=str(value["approval_id"]),
                tool_name=str(value["tool_name"]),
                title=str(value["title"]),
                summary=str(value["summary"]),
                status=str(value.get("status") or "pending"),
                destination_label=(
                    value["destination_label"]
                    if isinstance(value.get("destination_label"), str)
                    else None
                ),
                file_name=(
                    value["file_name"]
                    if isinstance(value.get("file_name"), str)
                    else None
                ),
                selected_title_count=(
                    value["selected_title_count"]
                    if isinstance(value.get("selected_title_count"), int)
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _to_langchain_tool(tool: Tool) -> StructuredTool:
    name = _bind_tool_name(tool.name)

    def _invoke() -> str:
        return tool.run({})

    return StructuredTool.from_function(
        func=_invoke,
        name=name,
        description=tool.description,
        args_schema=_EmptyToolArgs,
    )


def _tool_call_id(call: Mapping[str, object], index: int) -> str:
    raw = call.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return f"call_{index}_{uuid4().hex[:8]}"


def _final_text(messages: Sequence[object]) -> str | None:
    """Return the latest non-blank assistant text from *this* turn only.

    With a checkpointer, ``messages`` spans the whole thread. Bound the scan to
    messages after the last ``HumanMessage`` so a blank current answer cannot
    fall through and replay a prior turn's reply.
    """
    start = 0
    for index, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            start = index + 1
    for message in reversed(tuple(messages)[start:]):
        if not isinstance(message, AIMessage):
            continue
        tool_calls = getattr(message, "tool_calls", None) or ()
        if tool_calls:
            continue
        content = message.content
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = [
                part.get("text", "")
                if isinstance(part, Mapping)
                else str(part)
                for part in content
            ]
            joined = "".join(parts).strip()
            if joined:
                return joined
    return None


def _with_normalised_tool_calls(message: object) -> object:
    """Ensure assistant tool_calls are serialisable; fold invalid_tool_calls in."""
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
        else:
            name = "unknown"
            call_id = _tool_call_id({}, index)
        normalised.append(
            {
                "name": name,
                "args": {},
                "id": call_id,
                "error": _INVALID_TOOL_ARGS_MESSAGE,
            }
        )
        changed = True

    if not changed:
        return message
    return message.model_copy(
        update={"tool_calls": normalised, "invalid_tool_calls": []}
    )
