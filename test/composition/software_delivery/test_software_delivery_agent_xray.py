"""Agent orchestrate routes Xray targets to a bound, approval-gated Xray tool (#199)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from composition.software_delivery.agent import build_agent_orchestrate
from composition.software_delivery.chat import PackSoftwareDeliveryChat
from composition.xray_export.prepare import PreparedXrayExportCall, XrayDraftUnavailable
from domain.errors import ToolFailureError
from domain.models import AgentTurnResult
from domain.ports import Tool
from domain.tool_approval import ApprovalHints, PendingToolApproval
from packs.software_delivery.tools.create_xray_tests import TOOL_NAME as XRAY_TOOL
from packs.software_delivery.tools.export_test_cases_google_drive import (
    TOOL_NAME as DRIVE_TOOL,
)

XRAY_TARGET = "Create Xray tests from the selected Test Design test cases"
_RECEIPT = json.dumps({"created_keys": ["QA-1", "QA-2"], "created_count": 2, "failed_count": 1})


class _Agent:
    def __init__(self, *, pending: PendingToolApproval | None = None) -> None:
        self.pending = pending
        self.tools: list[Tool] = []
        self.runs = 0

    def run(self, goal: str, tools: Sequence[Tool], **_kwargs: object) -> AgentTurnResult:
        self.runs += 1
        self.tools = list(tools)
        if self.pending is not None:
            return AgentTurnResult(content="Waiting.", steps=0, pending_approval=self.pending)
        for tool in tools:
            tool.run({})
        return AgentTurnResult(content="Done.", steps=len(tools))


class _Invoke:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def __call__(self, tool_name: str, arguments: Mapping[str, object]) -> str:
        self.calls.append((tool_name, dict(arguments)))
        if tool_name == XRAY_TOOL:
            return _RECEIPT
        raise ToolFailureError(f"unexpected tool {tool_name}")


def _prepared() -> PreparedXrayExportCall:
    return PreparedXrayExportCall(
        tool_name=XRAY_TOOL, arguments={"draft_id": "draft-1"}, project_key="QA", test_count=3
    )


def _runner(agent: _Agent, invoke: _Invoke, *, prepare_xray=None) -> PackSoftwareDeliveryChat:
    return PackSoftwareDeliveryChat(
        allow_empty_evidence=True,
        retrieve=lambda _target: (),
        invoke=invoke,
        orchestrate=build_agent_orchestrate(
            agent,
            prepare_export=lambda _cid: (_ for _ in ()).throw(AssertionError("drive used")),
            prepare_xray=prepare_xray,
            max_steps=4,
        ),
    )


def test_xray_target_binds_only_the_xray_tool_with_approval_hints() -> None:
    agent, invoke = _Agent(), _Invoke()

    outcome = _runner(agent, invoke, prepare_xray=lambda _cid: _prepared()).run(
        XRAY_TARGET, conversation_id="conv-1", need_evidence=False
    )

    [tool] = agent.tools
    assert tool.name == XRAY_TOOL
    assert tool.approval_hints == ApprovalHints(  # type: ignore[attr-defined]
        title="Create Xray tests",
        summary=(
            "Create Jira Test issues in Xray from the generated Test Design cases. "
            "Each approval creates new tests; arguments stay on the server."
        ),
        destination_label="QA",
        selected_title_count=3,
    )
    assert invoke.calls == [(XRAY_TOOL, {"draft_id": "draft-1"})]
    assert "QA-1, QA-2" in outcome.answer
    assert outcome.run_view is not None
    [call] = outcome.run_view.calls
    assert call.tool_name == XRAY_TOOL
    assert call.summary == "Created 2 Xray tests in QA: QA-1, QA-2. 1 could not be created."
    assert outcome.run_view.drive_file_id == ""


def test_xray_pending_approval_is_projected_without_invoking() -> None:
    pending = PendingToolApproval(
        approval_id="ap-1", tool_name=XRAY_TOOL, title="Create Xray tests", summary="s"
    )
    agent, invoke = _Agent(pending=pending), _Invoke()

    outcome = _runner(agent, invoke, prepare_xray=lambda _cid: _prepared()).run(
        XRAY_TARGET, conversation_id="conv-1", need_evidence=False
    )

    assert invoke.calls == []
    assert outcome.pending_approval == pending
    assert "Xray" in outcome.answer


def test_xray_target_without_prepared_call_runs_no_agent() -> None:
    agent, invoke = _Agent(), _Invoke()

    outcome = _runner(
        agent, invoke, prepare_xray=lambda _cid: XrayDraftUnavailable()
    ).run(XRAY_TARGET, conversation_id="conv-1", need_evidence=False)

    assert agent.runs == 0
    assert "generated test cases" in outcome.answer


def test_xray_target_when_xray_is_not_wired_runs_no_agent() -> None:
    agent, invoke = _Agent(), _Invoke()

    outcome = _runner(agent, invoke).run(XRAY_TARGET, conversation_id="conv-1", need_evidence=False)

    assert agent.runs == 0
    assert "not available" in outcome.answer


def test_drive_target_never_binds_the_xray_tool() -> None:
    from composition.drive_export.prepare import PreparedDriveExportCall

    agent = _Agent()
    drive = PreparedDriveExportCall(
        tool_name=DRIVE_TOOL,
        arguments={"document_title": "K", "titles": ["A"], "folder_id": "root"},
        destination_label="Home",
        selected_title_count=1,
    )
    orchestrate = build_agent_orchestrate(
        agent,
        prepare_export=lambda _cid: drive,
        prepare_xray=lambda _cid: _prepared(),
        max_steps=4,
    )

    orchestrate(
        target="Export selected Test Design titles to Google Drive",
        hits=(),
        generate_tests=True,
        output_style="steps",
        invoke=lambda _n, _a: json.dumps({"file_id": "f", "file_name": "k.md"}),
        conversation_id="conv-1",
    )

    assert [tool.name for tool in agent.tools] == [DRIVE_TOOL]
