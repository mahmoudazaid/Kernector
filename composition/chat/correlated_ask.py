"""Bind a request_id around any grounded ask turn."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from application.contracts import AskRequest, AskResponse, RunMeta
from application.observability import bind_request_id, reset_request_id
from composition.software_delivery.tools import SoftwareDeliveryRunView
from composition.chat.tool_augmented_ask import GroundedAsk


class CorrelatedAsk:
    """Composition wrapper that correlates logs for one chat turn.

    Always wraps the final ``GroundedAsk`` returned to presentation — including
    when no domain pack is enabled — so ask / retrieve / tool logs share one
    ``request_id``. Reuses an already-bound outer id and restores it via
    ContextVar token reset. On success, stamps that id onto ``AskResponse.run``.
    When ``provider`` is set, stamps the effective LLM provider onto the run
    so stored transcripts keep accurate cost-fallback captions (#49).
    """

    def __init__(self, ask: GroundedAsk, *, provider: str | None = None) -> None:
        self._ask = ask
        self._provider = provider

    def consume_tool_run_view(self) -> SoftwareDeliveryRunView | None:
        """Forward the typed tool-run view side path when the inner ask exposes it."""
        consume = getattr(self._ask, "consume_tool_run_view", None)
        if consume is None:
            return None
        return consume()

    def consume_workflow_action(self) -> object | None:
        """Forward a post-routing workflow handoff action when present."""
        consume = getattr(self._ask, "consume_workflow_action", None)
        if consume is None:
            return None
        return consume()

    def consume_clarification_context(self) -> object | None:
        """Forward structured clarification context when present."""
        consume = getattr(self._ask, "consume_clarification_context", None)
        if consume is None:
            return None
        return consume()

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        """Execute ``ask`` under a bound (or reused) request correlation id."""
        request_id, token = bind_request_id()
        try:
            response = self._ask.execute(request, settings)
            run = response.run if response.run is not None else RunMeta()
            updates: dict[str, object] = {}
            if run.request_id != request_id:
                updates["request_id"] = request_id
            if self._provider is not None and run.provider != self._provider:
                updates["provider"] = self._provider
            if updates:
                run = replace(run, **updates)
            if run is response.run:
                return response
            return AskResponse(
                answer=response.answer,
                citations=response.citations,
                tool_outputs=response.tool_outputs,
                run=run,
                generation_hits=response.generation_hits,
            )
        finally:
            reset_request_id(token)
