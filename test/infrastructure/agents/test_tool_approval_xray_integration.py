"""HITL + real Xray tool with a fake importer and the default policy (#199)."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from domain.test_management.xray import XrayImportResult, XrayTestCreateSchema, XrayTestSpec
from domain.tool_approval import ApprovalHints, PendingToolApproval, ToolApprovalPolicy
from infrastructure.agents.langgraph_tool_agent import LangGraphToolAgent
from packs.software_delivery.tools.create_xray_tests import TOOL_NAME, CreateXrayTestsTool
from test.packs.software_delivery.tools.test_create_xray_tests import (
    _candidate,
    _draft,
    _manual_case,
)


class _Importer:
    def __init__(self) -> None:
        self.schema_calls = 0
        self.imports: list[tuple[XrayTestSpec, ...]] = []

    def schema(self) -> XrayTestCreateSchema:
        self.schema_calls += 1
        return XrayTestCreateSchema("QA", True, True, True)

    def import_tests(self, specs: Sequence[XrayTestSpec]) -> XrayImportResult:
        self.imports.append(tuple(specs))
        return XrayImportResult(created_keys=("QA-11",), failed_count=0)


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


def _tool(importer: _Importer) -> CreateXrayTestsTool:
    draft = _draft(candidates=(_candidate("cand-1"),), cases=(_manual_case("cand-1"),))
    return CreateXrayTestsTool(load_draft=lambda _id: draft, importer=importer)


def _model(final: str) -> _ScriptedModel:
    return _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "software_delivery__create_xray_tests",
                        "args": {"draft_id": "draft-1"},
                        "id": "xray-1",
                    }
                ],
            ),
            AIMessage(content=final),
        ]
    )


def _agent(model: _ScriptedModel) -> LangGraphToolAgent:
    return LangGraphToolAgent(
        system_prompt="system",
        model_factory=lambda **_: model,
        checkpointer=InMemorySaver(),
        workspace_id="ws-hitl",
        approval_policy=ToolApprovalPolicy(),
        pending_args={},
        approval_hints={
            TOOL_NAME: ApprovalHints(
                title="Create Xray tests",
                summary="Create Jira Test issues in Xray.",
                destination_label="QA",
                selected_title_count=1,
            )
        },
    )


def test_pending_and_reject_never_touch_the_importer() -> None:
    importer = _Importer()
    agent = _agent(_model("Cancelled."))

    pending = agent.run("create xray tests", [_tool(importer)], max_steps=4, conversation_id="c")

    assert isinstance(pending.pending_approval, PendingToolApproval)
    assert pending.pending_approval.tool_name == TOOL_NAME
    assert pending.pending_approval.destination_label == "QA"
    assert (importer.schema_calls, importer.imports) == (0, [])

    agent.resume_approval(
        conversation_id="c",
        approval_id=pending.pending_approval.approval_id,
        decision="reject",
    )

    assert (importer.schema_calls, importer.imports) == (0, [])


def test_approve_creates_once_and_replay_does_not_create_again() -> None:
    importer = _Importer()
    agent = _agent(_model("Created."))
    pending = agent.run("create xray tests", [_tool(importer)], max_steps=4, conversation_id="c")
    assert isinstance(pending.pending_approval, PendingToolApproval)
    approval_id = pending.pending_approval.approval_id

    agent.resume_approval(conversation_id="c", approval_id=approval_id, decision="approve")
    agent.resume_approval(conversation_id="c", approval_id=approval_id, decision="approve")

    assert len(importer.imports) == 1
