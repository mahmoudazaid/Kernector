"""Thin use case: run a tool-calling agent through the domain port."""

from __future__ import annotations

from collections.abc import Sequence

from application.errors import ApplicationValidationError
from domain.models import AgentTurnResult
from domain.ports import Tool, ToolCallingAgent


class RunToolAgent:
    """Delegates a multi-step tool loop to an injected ``ToolCallingAgent``."""

    def __init__(self, agent: ToolCallingAgent) -> None:
        self._agent = agent

    def execute(
        self,
        goal: str,
        tools: Sequence[Tool],
        *,
        max_steps: int,
    ) -> AgentTurnResult:
        """Run the agent for ``goal`` with ``tools``.

        Args:
            goal (str): Non-blank objective for the agent turn.
            tools (Sequence[Tool]): Bound tools the agent may invoke.
            max_steps (int): Hard cap on agent model steps; must be >= 1.

        Returns:
            AgentTurnResult: Final text and optional step count.

        Raises:
            ApplicationValidationError: ``goal`` is blank or ``max_steps`` invalid.
            ProviderError: Propagated from the agent.
            ConfigurationError: Propagated typed config failure from composition.
            ValueError: Propagated when the agent factory rejects a provider.
            ToolArgumentValidationError: Propagated from a tool.
            ToolFailureError: Propagated from a tool.
        """
        if not isinstance(goal, str) or not goal.strip():
            raise ApplicationValidationError("goal must be non-empty")
        if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
            raise ApplicationValidationError("max_steps must be an integer >= 1")
        return self._agent.run(goal, tools, max_steps=max_steps)
