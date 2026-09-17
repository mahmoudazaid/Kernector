"""Labelled non-RAG ask: ChatModel only, no retrieval or citations."""

from __future__ import annotations

from collections.abc import Mapping
import logging

from application.ask_service import AskService
from application.contracts import AskRequest, AskResponse, RunMeta
from application.errors import ApplicationValidationError, InputRejectedError
from application.general_answer_policy import GENERAL_ANSWER_SYSTEM
from application.input_safety import reject_unsafe_query
from application.observability import current_request_id, log_operation
from application.response_style_policy import compose_agent_system
from application.turn_routing import CONFIDENCE_GENERAL, RoutingKind

logger = logging.getLogger(__name__)


class AskGeneral:
    """Answer clearly general turns without retrieval.

    Depends only on :class:`AskService` / ``ChatModel``. Never retrieves,
    never emits citations, and labels the turn as ``general_answer``.
    """

    def __init__(
        self,
        ask_service: AskService,
        *,
        max_input_length: int = 32_000,
    ) -> None:
        self._ask_service = ask_service
        self._max_input_length = max_input_length

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        """Complete a non-RAG answer for ``request``.

        Args:
            request: Ask contract (query + optional history/style).
            settings: Optional generation settings (domain-allowlisted).

        Returns:
            AskResponse with empty citations and labelled RunMeta.
        """
        try:
            return self._execute(request, settings)
        except ApplicationValidationError:
            raise
        except Exception as error:
            log_operation(
                logger,
                operation="ask_general",
                outcome="error",
                level=logging.ERROR,
                error_type=type(error).__name__,
            )
            raise

    def _execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None,
    ) -> AskResponse:
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

        system = compose_agent_system(GENERAL_ANSWER_SYSTEM, request.response_style)
        result = self._ask_service.ask(
            system,
            request.query,
            settings=settings,
            history=request.history,
        )
        run = RunMeta(
            model=result.model,
            latency_ms=result.latency_ms,
            usage=result.usage,
            settings=result.settings,
            request_id=current_request_id(),
            outcome="success",
            hit_count=0,
            citation_count=0,
            path="general_answer",
            intent=RoutingKind.GENERAL_ANSWER.value,
            routing_confidence=CONFIDENCE_GENERAL,
            ambiguous=False,
            response_style=(
                None
                if request.response_style is None
                else request.response_style.value
            ),
        )
        log_operation(
            logger,
            operation="ask_general",
            outcome="success",
            path="general_answer",
            intent=RoutingKind.GENERAL_ANSWER.value,
            model=run.model,
            latency_ms=run.latency_ms,
        )
        return AskResponse(
            answer=result.content,
            citations=(),
            generation_hits=(),
            run=run,
        )


__all__ = ["AskGeneral"]
