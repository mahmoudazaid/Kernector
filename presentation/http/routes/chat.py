"""Versioned grounded chat ask route."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from application.contracts import AskRequest
from application.decide_tool_approval import DecideToolApprovalRequest
from composition.test_design import (
    SourceLocatorView,
    try_test_design_chat_handoff,
)
from domain.models import Message
from presentation.http.deps import (
    AskFactoryDep,
    ClearAgentThreadDep,
    SettingsDep,
    ShortTermMemoryRuntimeDep,
    TestDesignFacadeDep,
)
from presentation.http.errors import problem_responses
from presentation.http.schemas import (
    ChatAskRequest,
    ChatAskResponse,
    ChatExportDestinationRequest,
    ChatExportDestinationResponse,
    ToolApprovalDecisionRequest,
    ToolApprovalDecisionResponse,
    chat_workflow_action_response,
    citation_response,
    pending_tool_approval_response,
    run_meta_response,
    tool_run_response,
    tools_used_response,
)

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post(
    "/chat/ask",
    responses=problem_responses(405, 409, 422, 500, 502),
)
def chat_ask(
    body: ChatAskRequest,
    ask_factory: AskFactoryDep,
    settings: SettingsDep,
) -> ChatAskResponse:
    """Run one grounded ask turn, or a RAG-free Test Design handoff."""
    locator_view = None
    if body.source_locator is not None:
        locator_view = SourceLocatorView(
            provider=body.source_locator.provider,
            locator=body.source_locator.locator,
        )
    handoff = try_test_design_chat_handoff(
        settings=settings,
        query=body.query,
        source_locator=locator_view,
    )
    if handoff is not None:
        return ChatAskResponse(
            answer=handoff.answer,
            citations=[],
            tools_used=[],
            run=None,
            tool_run=None,
            action=chat_workflow_action_response(handoff.action),
            pending_approval=None,
        )

    runtime = body.runtime
    ask = ask_factory(runtime)
    request = AskRequest(
        query=body.query,
        history=tuple(
            Message(role=item.role, content=item.content) for item in body.history
        ),
        conversation_id=body.conversation_id,
    )
    ask_settings = None if runtime is None else dict(runtime.settings)
    response = ask.execute(request, ask_settings)
    consume = getattr(ask, "consume_tool_run_view", None)
    tool_view = consume() if callable(consume) else None
    pending = None if tool_view is None else getattr(tool_view, "pending_approval", None)
    return ChatAskResponse(
        answer=response.answer,
        citations=[citation_response(c) for c in response.citations],
        tools_used=tools_used_response(response.tool_outputs),
        run=run_meta_response(response.run),
        tool_run=None if tool_view is None else tool_run_response(tool_view),
        action=None,
        pending_approval=pending_tool_approval_response(pending),
    )


@router.post(
    "/chat/threads/{conversation_id}/approvals/{approval_id}",
    responses=problem_responses(404, 409, 422, 500, 502),
)
def decide_tool_approval(
    conversation_id: str,
    approval_id: str,
    body: ToolApprovalDecisionRequest,
    short_term_memory: ShortTermMemoryRuntimeDep,
) -> ToolApprovalDecisionResponse:
    """Approve or reject a pending high-impact tool call on this thread."""
    result = short_term_memory.decide_tool_approval().execute(
        DecideToolApprovalRequest(
            conversation_id=conversation_id,
            approval_id=approval_id,
            decision=body.decision,
        )
    )
    tool_view = None
    take_result = getattr(short_term_memory, "take_approval_result", None)
    raw_result = take_result(approval_id) if callable(take_result) else None
    if raw_result is not None:
        tool_view = _tool_run_view_from_approval_result(raw_result)

    if result.cancelled:
        answer = (
            "Understood. I cancelled the export and did not write anything "
            "to Google Drive."
        )
    elif result.pending_approval is not None:
        answer = result.turn.content
    elif tool_view is not None and tool_view.drive_file_id:
        answer = (
            "Export finished. The Markdown file is in your Google Drive "
            "destination."
        )
    else:
        # Prefer the resumed turn text so we never claim success after a no-op.
        answer = result.turn.content

    return ToolApprovalDecisionResponse(
        answer=answer,
        cancelled=result.cancelled,
        pending_approval=pending_tool_approval_response(result.pending_approval),
        tool_run=None if tool_view is None else tool_run_response(tool_view),
    )


def _tool_run_view_from_approval_result(raw: str):
    """Best-effort Drive receipt projection from a resumed tool JSON string."""
    import json

    from composition.software_delivery_tools import SoftwareDeliveryRunView
    from composition.tool_runs import ToolCallView

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    file_id = payload.get("file_id")
    file_name = payload.get("file_name")
    if not isinstance(file_id, str) and not isinstance(file_name, str):
        return None
    drive_file_id = file_id if isinstance(file_id, str) else ""
    drive_file_name = file_name if isinstance(file_name, str) else ""
    return SoftwareDeliveryRunView(
        summary="Exported test cases to Google Drive",
        calls=(
            ToolCallView(
                "software_delivery.export_test_cases_google_drive",
                ok=True,
                summary="Exported test cases to Google Drive",
            ),
        ),
        drive_file_id=drive_file_id,
        drive_file_name=drive_file_name,
    )


@router.put(
    "/chat/threads/{conversation_id}/export-destination",
    responses=problem_responses(404, 405, 422, 500),
)
def put_chat_export_destination(
    conversation_id: str,
    body: ChatExportDestinationRequest,
    facade: TestDesignFacadeDep,
) -> ChatExportDestinationResponse:
    """Save the Google Drive export folder for this conversation (no upload)."""
    label = facade.set_export_destination(
        conversation_id,
        folder_id=body.folder_id,
        destination_label=body.destination_label,
    )
    return ChatExportDestinationResponse(destination_label=label)


@router.delete(
    "/chat/threads/{conversation_id}/checkpoint",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problem_responses(422, 500),
    response_class=Response,
)
def clear_chat_thread_checkpoint(
    conversation_id: str,
    clear_thread: ClearAgentThreadDep,
) -> Response:
    """Clear short-term agent checkpoints for ``conversation_id`` (idempotent)."""
    clear_thread.execute(conversation_id=conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
