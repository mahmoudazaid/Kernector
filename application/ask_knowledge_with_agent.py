"""Grounded ask via a tool-calling agent that must retrieve before answering."""

from __future__ import annotations

from collections.abc import Mapping
import logging

from application.contracts import AskRequest, AskResponse, RunMeta
from application.errors import ApplicationValidationError, InputRejectedError
from application.grounded_rag_policy import (
    GROUNDED_RAG_SYSTEM,
    INSUFFICIENT_KNOWLEDGE_ANSWER,
)
from application.input_safety import reject_unsafe_query
from application.observability import current_request_id, log_operation
from application.response_style_policy import compose_agent_system
from application.retrieval_citation_channel import RetrievalCitationChannel
from application.run_tool_agent import RunToolAgent
from domain.ports import Tool, ToolCallingAgent

logger = logging.getLogger(__name__)

_DEFAULT_MAX_STEPS = 8

AGENT_GROUNDED_RETRIEVE_POLICY = (
    f"{GROUNDED_RAG_SYSTEM}\n\n"
    "Agentic retrieval rules:\n"
    "- You must call the knowledge.retrieve tool with a natural-language "
    "query before giving a final answer.\n"
    "- Do not answer from general knowledge or invent facts.\n"
    "- If retrieval returns no useful context, say the available knowledge "
    "is insufficient.\n"
    "- A final answer without a successful retrieve is not allowed."
)


class AskKnowledgeWithAgent:
    """Runs grounded Q&A as agent → retrieve tool → answer.

    Citations come only from the typed ``RetrievalCitationChannel``. When the
    channel has no citations after the turn (retrieve skipped or empty hits),
    returns ``INSUFFICIENT_KNOWLEDGE_ANSWER`` and ignores model prose.

    ``AskRequest.history`` is validated for length and input safety, then
    discarded: conversational context is server-owned via ``conversation_id``
    → the agent's short-term checkpointer (same pattern as ``settings`` —
    accepted for AskKnowledge parity, not applied here). Clients that need
    multi-turn continuity must send a non-blank ``conversation_id``.

    When the shared agent already has a pending tool approval for that
    ``conversation_id``, the adapter keeps HITL tool bindings and runs this
    turn without touching the interrupted checkpointer thread.
    """

    def __init__(
        self,
        agent: ToolCallingAgent,
        retrieve_tool: Tool,
        channel: RetrievalCitationChannel,
        *,
        max_steps: int = _DEFAULT_MAX_STEPS,
        max_input_length: int,
    ) -> None:
        self._run_agent = RunToolAgent(agent)
        self._retrieve_tool = retrieve_tool
        self._channel = channel
        self._max_steps = max_steps
        self._max_input_length = max_input_length

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        """Run the agent grounded turn for ``request``.

        ``settings`` is accepted for AskKnowledge parity; generation settings
        are owned by the bound agent model factory. ``request.history`` is
        validated then discarded — thread memory is ``conversation_id``.
        """
        del settings
        try:
            return self._execute(request)
        except ApplicationValidationError:
            raise
        except Exception as error:
            log_operation(
                logger,
                operation="ask",
                outcome="error",
                level=logging.ERROR,
                error_type=type(error).__name__,
                prompt_key=request.prompt_key,
            )
            raise

    def _execute(self, request: AskRequest) -> AskResponse:
        if len(request.query) > self._max_input_length:
            raise InputRejectedError(
                f"query must be at most {self._max_input_length} characters, "
                f"got {len(request.query)}"
            )
        for index, message in enumerate(request.history):
            if len(message.content) > self._max_input_length:
                raise InputRejectedError(
                    f"history[{index}] content must be at most "
                    f"{self._max_input_length} characters, "
                    f"got {len(message.content)}"
                )
        reject_unsafe_query(request.query)
        for message in request.history:
            reject_unsafe_query(message.content)

        self._channel.clear()
        turn = self._run_agent.execute(
            request.query,
            [self._retrieve_tool],
            max_steps=self._max_steps,
            conversation_id=request.conversation_id,
            system_prompt=compose_agent_system(
                AGENT_GROUNDED_RETRIEVE_POLICY,
                request.response_style,
            ),
        )
        citations = self._channel.drain()
        if not citations:
            log_operation(
                logger,
                operation="ask",
                outcome="insufficient",
                hit_count=0,
                prompt_key=request.prompt_key,
            )
            return AskResponse(
                answer=INSUFFICIENT_KNOWLEDGE_ANSWER,
                citations=(),
                run=RunMeta(
                    request_id=current_request_id(),
                    outcome="insufficient",
                    hit_count=0,
                    citation_count=0,
                    prompt_key=request.prompt_key,
                    response_style=(
                        None
                        if request.response_style is None
                        else request.response_style.value
                    ),
                ),
                generation_hits=(),
            )

        log_operation(
            logger,
            operation="ask",
            outcome="success",
            hit_count=len(citations),
            citation_count=len(citations),
            prompt_key=request.prompt_key,
        )
        return AskResponse(
            answer=turn.content,
            citations=citations,
            run=RunMeta(
                request_id=current_request_id(),
                outcome="success",
                hit_count=len(citations),
                citation_count=len(citations),
                prompt_key=request.prompt_key,
                response_style=(
                    None
                    if request.response_style is None
                    else request.response_style.value
                ),
            ),
            generation_hits=(),
        )
