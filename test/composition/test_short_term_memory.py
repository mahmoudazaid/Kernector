"""Process-scoped short-term memory runtime ownership (#213)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from application.contracts import AskRequest
from application.untrusted_text import agent_tool_system_prompt
from composition.container import build_tool_augmented_ask
from composition.short_term_memory import (
    ShortTermMemoryRuntime,
    build_short_term_memory_runtime,
)
from composition.prepare_drive_export import PreparedDriveExportCall
from composition.software_delivery_agent import build_agent_orchestrate
from composition.software_delivery_chat import PackSoftwareDeliveryChat
from composition.tool_augmented_ask import ToolAugmentedAsk
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
)
from domain.models import AgentTurnResult
from infrastructure.config import load_settings
from packs.software_delivery.chat_intent import ChatToolSelection
from packs.software_delivery.tools.export_test_cases_google_drive import TOOL_NAME


class _ScriptedChat:
    def __init__(self, messages: Sequence[object]) -> None:
        self._messages = list(messages)
        self.invoke_messages: list[object] = []

    def bind_tools(self, tools: Sequence[object], *args: object, **kwargs: object):
        del tools, args, kwargs
        return self

    def invoke(self, messages: object, **_kwargs: object) -> object:
        self.invoke_messages.append(messages)
        if not self._messages:
            raise AssertionError("script exhausted")
        return self._messages.pop(0)


class _Factory:
    def __init__(self, chat: _ScriptedChat) -> None:
        self._chat = chat

    def __call__(self, **_kwargs: object) -> _ScriptedChat:
        return self._chat


def _hit() -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(
                SourceReference("AUTH-101", "user_story"), extra={}
            ),
            index=0,
            content="MFA is required.",
        ),
        score=0.9,
    )


def _prepared(_conversation_id: str) -> PreparedDriveExportCall:
    return PreparedDriveExportCall(
        tool_name=TOOL_NAME,
        arguments={
            "document_title": "KERN-482",
            "titles": ["Login MFA"],
            "folder_id": "folder-abc",
        },
        destination_label="QA",
        selected_title_count=1,
    )


def _ask_stack(
    runtime: ShortTermMemoryRuntime,
    chat: _ScriptedChat,
) -> ToolAugmentedAsk:
    agent = runtime.bind_tool_agent(
        system_prompt=agent_tool_system_prompt(),
        model_factory=_Factory(chat),
    )
    runner = PackSoftwareDeliveryChat(
        retrieve=lambda _target: (_hit(),),
        invoke=lambda _name, _args: (
            '{"file_id":"f1","file_name":"x.md"}'
        ),
        orchestrate=build_agent_orchestrate(
            agent, prepare_export=_prepared, max_steps=4
        ),
    )
    return ToolAugmentedAsk(
        ask=lambda request, settings=None: (_ for _ in ()).throw(
            AssertionError("RAG must not run")
        ),
        runner=runner,
        select=lambda _query: ChatToolSelection(
            generate_tests=True, output_style="steps"
        ),
        pack_id="software-delivery",
    )


def test_build_runtime_disabled_when_agent_loop_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SOFTWARE_DELIVERY_AGENT_LOOP", raising=False)
    runtime = build_short_term_memory_runtime(load_settings())
    assert runtime.enabled is False
    runtime.clear_use_case().execute(conversation_id="conv-1")


def test_build_runtime_disabled_when_workspace_id_missing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("SOFTWARE_DELIVERY_AGENT_LOOP", "true")
    monkeypatch.delenv("DOCUMENT_CATALOG_WORKSPACE_ID", raising=False)
    with caplog.at_level("WARNING", logger="composition.short_term_memory"):
        runtime = build_short_term_memory_runtime(load_settings())
    assert runtime.enabled is False
    assert runtime.short_term_memory_enabled is False
    assert any("Short-term memory disabled" in record.message for record in caplog.records)
    runtime.clear_use_case().execute(conversation_id="conv-1")


def test_shared_runtime_reuses_state_across_independently_built_stacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOFTWARE_DELIVERY_AGENT_LOOP", "true")
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "test-workspace")
    runtime = build_short_term_memory_runtime(load_settings())
    assert runtime.enabled is True

    chat_a = _ScriptedChat([AIMessage(content="first")])
    chat_b = _ScriptedChat([AIMessage(content="second")])
    stack_a = _ask_stack(runtime, chat_a)
    stack_b = _ask_stack(runtime, chat_b)

    stack_a.execute(
        AskRequest(query="Score the risk for AUTH-101", conversation_id="conv-1")
    )
    stack_b.execute(
        AskRequest(query="Score the risk for AUTH-101 again", conversation_id="conv-1")
    )

    follow = chat_b.invoke_messages[0]
    assert any(
        isinstance(m, HumanMessage) and "AUTH-101" in str(m.content)
        for m in follow
    )
    # First-turn human content from stack A must appear in stack B model input.
    assert any("Score the risk for AUTH-101" in str(getattr(m, "content", "")) for m in follow)


def test_clear_thread_evicts_hitl_maps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOFTWARE_DELIVERY_AGENT_LOOP", "true")
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "test-workspace")
    runtime = build_short_term_memory_runtime(load_settings())
    assert runtime.enabled is True

    runtime._pending_args["appr-A"] = {"folder_id": "SECRET", "titles": ["t1"]}
    runtime._approval_results["appr-A"] = '{"file_id":"f1"}'
    runtime._approvals_by_conversation["conv-A"] = {"appr-A"}
    runtime._tools_by_conversation["conv-A"] = {"tool": object()}  # type: ignore[dict-item]
    runtime._approval_ledger.record("appr-A", "approve")
    runtime._pending_args["appr-B"] = {"folder_id": "other"}
    runtime._approvals_by_conversation["conv-B"] = {"appr-B"}

    runtime.clear_use_case().execute(conversation_id="conv-A")

    assert "appr-A" not in runtime._pending_args
    assert "appr-A" not in runtime._approval_results
    assert "conv-A" not in runtime._tools_by_conversation
    assert "conv-A" not in runtime._approvals_by_conversation
    assert runtime._approval_ledger.recorded("appr-A") is None
    assert runtime._pending_args["appr-B"]["folder_id"] == "other"
    assert runtime._approvals_by_conversation["conv-B"] == {"appr-B"}


def test_fresh_runtime_does_not_see_prior_checkpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOFTWARE_DELIVERY_AGENT_LOOP", "true")
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "test-workspace")
    first = build_short_term_memory_runtime(load_settings())
    chat_a = _ScriptedChat([AIMessage(content="first")])
    _ask_stack(first, chat_a).execute(
        AskRequest(query="Score the risk for AUTH-101", conversation_id="conv-1")
    )

    second = build_short_term_memory_runtime(load_settings())
    chat_b = _ScriptedChat([AIMessage(content="fresh")])
    _ask_stack(second, chat_b).execute(
        AskRequest(query="Score the risk for AUTH-101 again", conversation_id="conv-1")
    )

    follow = chat_b.invoke_messages[0]
    humans = [
        str(m.content)
        for m in follow
        if isinstance(m, HumanMessage)
    ]
    assert len(humans) == 1
    assert "again" in humans[0]
