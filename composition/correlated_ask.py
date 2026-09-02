"""Bind a request_id around any grounded ask turn."""

from __future__ import annotations

from collections.abc import Mapping

from application.contracts import AskRequest, AskResponse
from application.observability import bind_request_id, reset_request_id
from composition.tool_augmented_ask import GroundedAsk


class CorrelatedAsk:
    """Composition wrapper that correlates logs for one chat turn.

    Always wraps the final ``GroundedAsk`` returned to presentation — including
    when no domain pack is enabled — so ask / retrieve / tool logs share one
    ``request_id``. Reuses an already-bound outer id and restores it via
    ContextVar token reset.
    """

    def __init__(self, ask: GroundedAsk) -> None:
        self._ask = ask

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        """Execute ``ask`` under a bound (or reused) request correlation id."""
        _request_id, token = bind_request_id()
        try:
            return self._ask.execute(request, settings)
        finally:
            reset_request_id(token)
