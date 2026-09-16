"""HITL + real Drive export tool with fake ArtifactUploader (#214)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from domain.artifacts import Artifact, ArtifactReceipt
from domain.tool_approval import ApprovalHints, PendingToolApproval, ToolApprovalPolicy
from infrastructure.agents.langgraph_tool_agent import LangGraphToolAgent
from packs.software_delivery.tools.export_test_cases_google_drive import (
    TOOL_NAME,
    ExportTestCasesGoogleDriveTool,
)


class _FakeUploader:
    def __init__(self) -> None:
        self.calls: list[tuple[Artifact, str]] = []

    def upload(self, artifact: Artifact, *, parent_id: str) -> ArtifactReceipt:
        self.calls.append((artifact, parent_id))
        return ArtifactReceipt(artifact_id="file-hitl", file_name=artifact.file_name)


def _drive_tool(uploader: _FakeUploader) -> ExportTestCasesGoogleDriveTool:
    def render(document_title: str, titles: Sequence[str]) -> str:
        lines = [f"# {document_title}", "", "## Selected tests", ""]
        lines.extend(f"- {title}" for title in titles)
        return "\n".join(lines) + "\n"

    return ExportTestCasesGoogleDriveTool(render=render, uploader=uploader)


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


def _agent(model: _ScriptedModel) -> LangGraphToolAgent:
    return LangGraphToolAgent(
        system_prompt="system",
        model_factory=lambda **_: model,
        checkpointer=InMemorySaver(),
        workspace_id="ws-hitl",
        approval_policy=ToolApprovalPolicy(frozenset({TOOL_NAME})),
        pending_args={},
        approval_hints={
            TOOL_NAME: ApprovalHints(
                title="Export test cases to Google Drive",
                summary="Write selected titles as Markdown.",
                destination_label="QA / Sprint 3",
                file_name="issue-482.md",
                selected_title_count=2,
            )
        },
    )


_ARGS: Mapping[str, object] = {
    "document_title": "Issue 482",
    "titles": ["Login with MFA", "Checkout fails"],
    "folder_id": "folderExport123",
    "file_name": "issue-482.md",
}


def test_pending_and_reject_upload_zero_times() -> None:
    uploader = _FakeUploader()
    tool = _drive_tool(uploader)
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "software_delivery__export_test_cases_google_drive",
                        "args": dict(_ARGS),
                        "id": "drive-1",
                    }
                ],
            ),
            AIMessage(content="Cancelled."),
        ]
    )
    agent = _agent(model)
    pending = agent.run("export", [tool], max_steps=4, conversation_id="conv-1")
    assert isinstance(pending.pending_approval, PendingToolApproval)
    assert uploader.calls == []

    result = agent.resume_approval(
        conversation_id="conv-1",
        approval_id=pending.pending_approval.approval_id,
        decision="reject",
    )
    assert uploader.calls == []
    assert result.pending_approval is None


def test_approve_uploads_once_and_replay_stays_one() -> None:
    uploader = _FakeUploader()
    tool = _drive_tool(uploader)
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "software_delivery__export_test_cases_google_drive",
                        "args": dict(_ARGS),
                        "id": "drive-1",
                    }
                ],
            ),
            AIMessage(content="Exported."),
        ]
    )
    agent = _agent(model)
    pending = agent.run("export", [tool], max_steps=4, conversation_id="conv-1")
    assert isinstance(pending.pending_approval, PendingToolApproval)
    assert uploader.calls == []
    approval_id = pending.pending_approval.approval_id

    first = agent.resume_approval(
        conversation_id="conv-1",
        approval_id=approval_id,
        decision="approve",
    )
    assert len(uploader.calls) == 1
    artifact, parent_id = uploader.calls[0]
    assert parent_id == "folderExport123"
    assert artifact.file_name == "issue-482.md"
    assert first.pending_approval is None
    assert "folder" not in first.content.lower()

    second = agent.resume_approval(
        conversation_id="conv-1",
        approval_id=approval_id,
        decision="approve",
    )
    assert len(uploader.calls) == 1
    assert second.pending_approval is None
