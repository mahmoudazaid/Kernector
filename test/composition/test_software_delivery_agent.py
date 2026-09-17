"""Agent-backed Software Delivery orchestrate for PackSoftwareDeliveryChat."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from application.contracts import InvokeToolResponse
from composition.prepare_drive_export import (
    DraftUnavailable,
    PreparedDriveExportCall,
)
from composition.software_delivery_agent import build_agent_orchestrate
from composition.software_delivery_chat import PackSoftwareDeliveryChat
from domain.errors import ToolFailureError
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
)
from domain.models import AgentTurnResult
from domain.ports import Tool
from packs.software_delivery.tools.export_test_cases_google_drive import TOOL_NAME

_DRIVE_RECEIPT = json.dumps({"file_id": "file-1", "file_name": "issue-482.md"})


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


class _OrderedFakeAgent:
    def __init__(self, tool_names: Sequence[str], *, truncated: bool = False) -> None:
        self._tool_names = tuple(tool_names)
        self._truncated = truncated
        self.seen_tools: list[str] = []

    def run(
        self,
        goal: str,
        tools: Sequence[Tool],
        *,
        max_steps: int,
        conversation_id: str | None = None,
        system_prompt: str | None = None,
    ) -> AgentTurnResult:
        del goal, max_steps, conversation_id, system_prompt
        by_name = {tool.name: tool for tool in tools}
        self.seen_tools = list(by_name)
        for name in self._tool_names:
            by_name[name].run({})
        return AgentTurnResult(
            content="Agent finished.",
            steps=len(self._tool_names),
            truncated=self._truncated,
        )


@dataclass(frozen=True, slots=True)
class _Prepared:
    value: object

    def __call__(self, conversation_id: str) -> object:
        del conversation_id
        return self.value


def _invoke(tool_name: str, arguments: Mapping[str, object]) -> str:
    if tool_name == TOOL_NAME:
        assert arguments["folder_id"] == "folder-abc"
        assert arguments["titles"] == ["Login MFA"]
        return _DRIVE_RECEIPT
    raise ToolFailureError(f"unknown tool {tool_name}")


def test_agent_defaults_to_home_destination_when_none_persisted() -> None:
    prepared = PreparedDriveExportCall(
        tool_name=TOOL_NAME,
        arguments={
            "document_title": "KERN-482",
            "titles": ["Login MFA"],
            "folder_id": "root",
        },
        destination_label="Home",
        selected_title_count=1,
    )

    def _home_invoke(tool_name: str, arguments: Mapping[str, object]) -> str:
        if tool_name == TOOL_NAME:
            assert arguments["folder_id"] == "root"
            return _DRIVE_RECEIPT
        raise ToolFailureError(f"unknown tool {tool_name}")

    agent = _OrderedFakeAgent((TOOL_NAME,))
    runner = PackSoftwareDeliveryChat(
        allow_empty_evidence=True,
        retrieve=lambda _target: (),
        invoke=_home_invoke,
        orchestrate=build_agent_orchestrate(
            agent, prepare_export=_Prepared(prepared), max_steps=4
        ),
    )

    outcome = runner.run(
        "Export selected tests to Google Drive",
        conversation_id="conv-1",
    )

    assert outcome.run_view is not None
    assert outcome.run_view.export_destination_required is False
    assert agent.seen_tools == [TOOL_NAME]


def test_agent_exports_drive_when_prepared_call_available() -> None:
    prepared = PreparedDriveExportCall(
        tool_name=TOOL_NAME,
        arguments={
            "document_title": "KERN-482",
            "titles": ["Login MFA"],
            "folder_id": "folder-abc",
        },
        destination_label="QA / Sprint 3",
        selected_title_count=1,
    )
    agent = _OrderedFakeAgent((TOOL_NAME,))
    runner = PackSoftwareDeliveryChat(
        allow_empty_evidence=True,
        retrieve=lambda _target: (),
        invoke=_invoke,
        orchestrate=build_agent_orchestrate(
            agent, prepare_export=_Prepared(prepared), max_steps=4
        ),
    )

    outcome = runner.run(
        "Export selected tests to Google Drive",
        conversation_id="conv-1",
    )

    assert outcome.tool_outputs == (InvokeToolResponse(TOOL_NAME, _DRIVE_RECEIPT),)
    assert outcome.run_view is not None
    assert outcome.run_view.drive_file_id == "file-1"
    assert outcome.run_view.drive_file_name == "issue-482.md"
    assert outcome.run_view.drive_destination_label == "QA / Sprint 3"
    assert agent.seen_tools == [TOOL_NAME]


def test_agent_does_not_bind_retired_tools() -> None:
    prepared = PreparedDriveExportCall(
        tool_name=TOOL_NAME,
        arguments={
            "document_title": "KERN-482",
            "titles": ["Login MFA"],
            "folder_id": "folder-abc",
        },
        destination_label="QA",
        selected_title_count=1,
    )
    agent = _OrderedFakeAgent((TOOL_NAME,))
    PackSoftwareDeliveryChat(
        allow_empty_evidence=True,
        retrieve=lambda _target: (),
        invoke=_invoke,
        orchestrate=build_agent_orchestrate(
            agent, prepare_export=_Prepared(prepared)
        ),
    ).run("Export to Google Drive", conversation_id="conv-1")

    assert agent.seen_tools == [TOOL_NAME]
    assert "software_delivery.risk_score" not in agent.seen_tools
    assert "software_delivery.generate_test_cases" not in agent.seen_tools
    assert "software_delivery.export_test_cases_markdown" not in agent.seen_tools


def test_agent_draft_unavailable_skips_tools() -> None:
    agent = _OrderedFakeAgent((TOOL_NAME,))
    outcome = PackSoftwareDeliveryChat(
        allow_empty_evidence=True,
        retrieve=lambda _target: (),
        invoke=_invoke,
        orchestrate=build_agent_orchestrate(
            agent, prepare_export=_Prepared(DraftUnavailable())
        ),
    ).run("Export to Google Drive", conversation_id="conv-1")

    assert outcome.tool_outputs == ()
    assert agent.seen_tools == []
