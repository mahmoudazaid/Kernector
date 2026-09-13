"""Versioned grounded chat ask route."""

from __future__ import annotations

from fastapi import APIRouter

from application.contracts import AskRequest
from composition.test_design import (
    SourceReferenceView,
    resolve_start_test_design_action,
)
from domain.models import Message
from presentation.http.deps import AskFactoryDep, SettingsDep
from presentation.http.errors import problem_responses
from presentation.http.schemas import (
    ChatAskRequest,
    ChatAskResponse,
    chat_workflow_action_response,
    citation_response,
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
    """Run one grounded ask turn through composition."""
    runtime = body.runtime
    ask = ask_factory(runtime)
    request = AskRequest(
        query=body.query,
        history=tuple(
            Message(role=item.role, content=item.content) for item in body.history
        ),
    )
    ask_settings = None if runtime is None else dict(runtime.settings)
    response = ask.execute(request, ask_settings)
    consume = getattr(ask, "consume_tool_run_view", None)
    tool_view = consume() if callable(consume) else None
    source_view = None
    if body.source_reference is not None:
        source_view = SourceReferenceView(
            source_id=body.source_reference.source_id,
            source_type=body.source_reference.source_type,
        )
    action = resolve_start_test_design_action(
        settings=settings,
        source_reference=source_view,
        ticket_identifier=body.ticket_identifier,
    )
    return ChatAskResponse(
        answer=response.answer,
        citations=[citation_response(c) for c in response.citations],
        tools_used=tools_used_response(response.tool_outputs),
        run=run_meta_response(response.run),
        tool_run=None if tool_view is None else tool_run_response(tool_view),
        action=None if action is None else chat_workflow_action_response(action),
    )
