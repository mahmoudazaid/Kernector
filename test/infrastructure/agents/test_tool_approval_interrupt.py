"""HITL interrupt before Tool.run (#214)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from domain.tool_approval import ApprovalHints, ToolApprovalPolicy
from domain.models import AgentTurnResult
from domain.ports import Tool
from domain.tool_approval import PendingToolApproval
from infrastructure.agents.langgraph_tool_agent import LangGraphToolAgent
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import AIMessage


class _CountingTool:
    def __init__(self, name: str) -> None:
        self._name = name
        self.calls = 0
        self.approval_hints = ApprovalHints(
            title="Export test cases to Google Drive",
            summary="Write selected titles as Markdown.",
            destination_label="QA / Sprint 3",
            file_name="issue-482.md",
            selected_title_count=3,
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "risky tool"

    def run(self, arguments: Mapping[str, object]) -> str:
        del arguments
        self.calls += 1
        return '{"file_id":"f1","file_name":"issue-482.md"}'


class _SafeTool:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "software_delivery.safe_tool"

    @property
    def description(self) -> str:
        return "safe"

    def run(self, arguments: Mapping[str, object]) -> str:
        del arguments
        self.calls += 1
        return "ok"


class _ScriptedModel:
    def __init__(self, messages: Sequence[object]) -> None:
        self._messages = list(messages)

    def bind_tools(self, tools: Sequence[object], *args: object, **kwargs: object):
        del tools, args, kwargs
        return self

    def invoke(self, messages: object, **_kwargs: object) -> object:
        del messages
        if not self._messages:
            return AIMessage(content="done")
        return self._messages.pop(0)


def _agent(
    model: _ScriptedModel,
    *,
    policy: ToolApprovalPolicy | None = None,
) -> LangGraphToolAgent:
    pending: dict[str, Mapping[str, object]] = {}
    return LangGraphToolAgent(
        system_prompt="system",
        model_factory=lambda **_: model,
        checkpointer=InMemorySaver(),
        workspace_id="ws-a",
        approval_policy=policy
        or ToolApprovalPolicy(
            frozenset({"software_delivery.export_test_cases_google_drive"})
        ),
        pending_args=pending,
    )


def test_risky_tool_interrupts_before_run_with_zero_calls() -> None:
    tool = _CountingTool("software_delivery.export_test_cases_google_drive")
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "software_delivery__export_test_cases_google_drive",
                        "args": {},
                        "id": "c1",
                    }
                ],
            )
        ]
    )
    agent = _agent(model)
    turn = agent.run("export", [tool], max_steps=4, conversation_id="conv-1")

    assert tool.calls == 0
    assert isinstance(turn.pending_approval, PendingToolApproval)
    assert turn.pending_approval.tool_name == tool.name
    assert turn.pending_approval.destination_label == "QA / Sprint 3"
    assert turn.pending_approval.file_name == "issue-482.md"
    assert turn.pending_approval.selected_title_count == 3
    assert "folder" not in turn.content.lower()


def test_pending_file_name_from_bound_arguments_when_hints_omit_it() -> None:
    class _BoundExport:
        def __init__(self) -> None:
            self.calls = 0
            self._arguments = {
                "document_title": "KERN-482",
                "titles": ["A", "B"],
                "folder_id": "root",
                "file_name": "KERN-482.md",
            }
            self.approval_hints = ApprovalHints(
                title="Export test cases to Google Drive",
                summary="Write selected titles as Markdown.",
                destination_label="Home",
                file_name=None,
                selected_title_count=2,
            )

        @property
        def name(self) -> str:
            return "software_delivery.export_test_cases_google_drive"

        @property
        def description(self) -> str:
            return "risky"

        def run(self, arguments: Mapping[str, object]) -> str:
            del arguments
            self.calls += 1
            return '{"file_id":"f1","file_name":"KERN-482.md"}'

    tool = _BoundExport()
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "software_delivery__export_test_cases_google_drive",
                        "args": {},
                        "id": "c-bound",
                    }
                ],
            )
        ]
    )
    agent = _agent(model)
    turn = agent.run("export", [tool], max_steps=4, conversation_id="conv-bound")
    assert tool.calls == 0
    assert turn.pending_approval is not None
    assert turn.pending_approval.file_name == "KERN-482.md"
    assert turn.pending_approval.destination_label == "Home"


def test_reject_completes_without_tool_invocation() -> None:
    tool = _CountingTool("software_delivery.export_test_cases_google_drive")
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "software_delivery__export_test_cases_google_drive",
                        "args": {},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(content="Cancelled."),
        ]
    )
    agent = _agent(model)
    pending = agent.run("export", [tool], max_steps=4, conversation_id="conv-1")
    assert isinstance(pending.pending_approval, PendingToolApproval)

    result = agent.resume_approval(
        conversation_id="conv-1",
        approval_id=pending.pending_approval.approval_id,
        decision="reject",
    )
    assert tool.calls == 0
    assert result.pending_approval is None
    assert "cancel" in result.content.lower() or result.content


def test_approve_invokes_tool_once() -> None:
    tool = _CountingTool("software_delivery.export_test_cases_google_drive")
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "software_delivery__export_test_cases_google_drive",
                        "args": {},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(content="Exported."),
        ]
    )
    agent = _agent(model)
    pending = agent.run("export", [tool], max_steps=4, conversation_id="conv-1")
    assert isinstance(pending.pending_approval, PendingToolApproval)

    result = agent.resume_approval(
        conversation_id="conv-1",
        approval_id=pending.pending_approval.approval_id,
        decision="approve",
    )
    assert tool.calls == 1
    assert result.pending_approval is None
    assert "Exported" in result.content


def test_non_risky_tool_runs_without_interrupt() -> None:
    tool = _SafeTool()
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "software_delivery__safe_tool",
                        "args": {},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(content="Done."),
        ]
    )
    agent = _agent(model)
    turn = agent.run("go", [tool], max_steps=4, conversation_id="conv-1")
    assert tool.calls == 1
    assert turn.pending_approval is None
    assert isinstance(turn, AgentTurnResult)


def test_approve_replay_does_not_invoke_tool_twice() -> None:
    tool = _CountingTool("software_delivery.export_test_cases_google_drive")
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "software_delivery__export_test_cases_google_drive",
                        "args": {},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(content="Exported."),
        ]
    )
    agent = _agent(model)
    pending = agent.run("export", [tool], max_steps=4, conversation_id="conv-1")
    assert isinstance(pending.pending_approval, PendingToolApproval)
    approval_id = pending.pending_approval.approval_id

    first = agent.resume_approval(
        conversation_id="conv-1",
        approval_id=approval_id,
        decision="approve",
    )
    second = agent.resume_approval(
        conversation_id="conv-1",
        approval_id=approval_id,
        decision="approve",
    )
    assert tool.calls == 1
    assert first.pending_approval is None
    assert second.pending_approval is None


def test_pending_approval_is_isolated_across_conversations() -> None:
    tool_a = _CountingTool("software_delivery.export_test_cases_google_drive")
    tool_b = _CountingTool("software_delivery.export_test_cases_google_drive")
    model_a = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "software_delivery__export_test_cases_google_drive",
                        "args": {},
                        "id": "ca",
                    }
                ],
            )
        ]
    )
    model_b = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "software_delivery__export_test_cases_google_drive",
                        "args": {},
                        "id": "cb",
                    }
                ],
            )
        ]
    )
    pending_args: dict[str, Mapping[str, object]] = {}
    agent_a = LangGraphToolAgent(
        system_prompt="system",
        model_factory=lambda **_: model_a,
        checkpointer=InMemorySaver(),
        workspace_id="ws-a",
        approval_policy=ToolApprovalPolicy(
            frozenset({"software_delivery.export_test_cases_google_drive"})
        ),
        pending_args=pending_args,
    )
    # Separate checkpointer simulates separate process-scoped threads for
    # isolation of conversation ids under the same workspace.
    agent_b = LangGraphToolAgent(
        system_prompt="system",
        model_factory=lambda **_: model_b,
        checkpointer=InMemorySaver(),
        workspace_id="ws-a",
        approval_policy=ToolApprovalPolicy(
            frozenset({"software_delivery.export_test_cases_google_drive"})
        ),
        pending_args={},
    )
    pending_a = agent_a.run("export", [tool_a], max_steps=4, conversation_id="conv-a")
    pending_b = agent_b.run("export", [tool_b], max_steps=4, conversation_id="conv-b")
    assert isinstance(pending_a.pending_approval, PendingToolApproval)
    assert isinstance(pending_b.pending_approval, PendingToolApproval)

    agent_a.resume_approval(
        conversation_id="conv-a",
        approval_id=pending_a.pending_approval.approval_id,
        decision="reject",
    )
    assert tool_a.calls == 0
    assert tool_b.calls == 0
    assert pending_b.pending_approval is not None


def test_resume_rejects_approval_owned_by_another_conversation() -> None:
    """Cross-conversation approve must not resume the wrong thread (#311)."""
    from domain.errors import ToolApprovalNotFoundError

    tool = _CountingTool("software_delivery.export_test_cases_google_drive")
    pending_args: dict[str, Mapping[str, object]] = {}
    approvals_by_conversation: dict[str, set[str]] = {}
    tools_by_conversation: dict[str, dict[str, Tool]] = {}
    checkpointer = InMemorySaver()
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "software_delivery__export_test_cases_google_drive",
                        "args": {},
                        "id": "tc-A",
                    }
                ],
            ),
            AIMessage(content="plain answer for B"),
        ]
    )
    agent = LangGraphToolAgent(
        system_prompt="system",
        model_factory=lambda **_: model,
        checkpointer=checkpointer,
        workspace_id="ws-a",
        approval_policy=ToolApprovalPolicy(
            frozenset({"software_delivery.export_test_cases_google_drive"})
        ),
        pending_args=pending_args,
        approvals_by_conversation=approvals_by_conversation,
        tools_by_conversation=tools_by_conversation,
    )
    pending_a = agent.run("export", [tool], max_steps=4, conversation_id="conv-A")
    assert isinstance(pending_a.pending_approval, PendingToolApproval)
    approval_id = pending_a.pending_approval.approval_id

    turn_b = agent.run("hello", [tool], max_steps=4, conversation_id="conv-B")
    assert turn_b.pending_approval is None
    assert "plain answer for B" in turn_b.content

    with pytest.raises(ToolApprovalNotFoundError):
        agent.resume_approval(
            conversation_id="conv-B",
            approval_id=approval_id,
            decision="approve",
        )
    assert tool.calls == 0
    assert approval_id in pending_args
    assert approvals_by_conversation.get("conv-A") == {approval_id}


def test_pending_approval_survives_interleaved_grounded_ask_on_same_conversation() -> None:
    """Grounded ask must not clobber export HITL tool bindings (#328)."""

    class _RetrieveTool:
        args_schema: type | None = None

        @property
        def name(self) -> str:
            return "knowledge.retrieve"

        @property
        def description(self) -> str:
            return "retrieve"

        def run(self, arguments: Mapping[str, object]) -> str:
            del arguments
            return "ctx"

    export = _CountingTool("software_delivery.export_test_cases_google_drive")
    retrieve = _RetrieveTool()
    tools_by_conversation: dict[str, dict[str, Tool]] = {}
    pending_args: dict[str, Mapping[str, object]] = {}
    approvals_by_conversation: dict[str, set[str]] = {}
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "software_delivery__export_test_cases_google_drive",
                        "args": {},
                        "id": "tc-export",
                    }
                ],
            ),
            AIMessage(content="grounded answer without retrieve call"),
            AIMessage(content="export done"),
        ]
    )
    agent = LangGraphToolAgent(
        system_prompt="system",
        model_factory=lambda **_: model,
        checkpointer=InMemorySaver(),
        workspace_id="ws-a",
        approval_policy=ToolApprovalPolicy(
            frozenset({"software_delivery.export_test_cases_google_drive"})
        ),
        pending_args=pending_args,
        approvals_by_conversation=approvals_by_conversation,
        tools_by_conversation=tools_by_conversation,
    )

    pending = agent.run("export please", [export], max_steps=4, conversation_id="conv-1")
    assert isinstance(pending.pending_approval, PendingToolApproval)
    approval_id = pending.pending_approval.approval_id
    assert list(tools_by_conversation["conv-1"]) == [export.name]

    grounded = agent.run(
        "what is in the docs?",
        [retrieve],
        max_steps=4,
        conversation_id="conv-1",
    )
    assert grounded.pending_approval is None
    assert "grounded answer" in grounded.content
    assert list(tools_by_conversation["conv-1"]) == [export.name]

    resumed = agent.resume_approval(
        conversation_id="conv-1",
        approval_id=approval_id,
        decision="approve",
    )
    assert resumed.pending_approval is None
    assert export.calls == 1
    assert "export done" in resumed.content
