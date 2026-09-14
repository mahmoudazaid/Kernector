"""Versioned grounded chat ask route."""

from __future__ import annotations

from fastapi import APIRouter

from application.contracts import AskRequest
from composition.test_design import (
    SourceLocatorView,
    try_test_design_chat_handoff,
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
        )

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
    return ChatAskResponse(
        answer=response.answer,
        citations=[citation_response(c) for c in response.citations],
        tools_used=tools_used_response(response.tool_outputs),
        run=run_meta_response(response.run),
        tool_run=None if tool_view is None else tool_run_response(tool_view),
        action=None,
    )
