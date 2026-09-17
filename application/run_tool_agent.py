"""Thin use case: run a tool-calling agent through the domain port."""

from __future__ import annotations

from collections.abc import Sequence

from application.errors import ApplicationValidationError
from application.thread_memory import require_conversation_id
from domain.models import AgentTurnResult
from domain.ports import AgentThreadMemory, Tool, ToolCallingAgent


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
        conversation_id: str | None = None,
        system_prompt: str | None = None,
    ) -> AgentTurnResult:
        """Run the agent for ``goal`` with ``tools``.

        Args:
            goal (str): Non-blank objective for the agent turn.
            tools (Sequence[Tool]): Bound tools the agent may invoke.
            max_steps (int): Hard cap on agent model steps; must be >= 1.
            conversation_id (str | None): Optional client conversation key for
                short-term thread memory.
            system_prompt (str | None): Optional per-invocation system prompt
                override (style composition). Does not mutate the agent.

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
        validated_conversation: str | None = None
        if conversation_id is not None:
            validated_conversation = require_conversation_id(conversation_id)
        return self._agent.run(
            goal,
            tools,
            max_steps=max_steps,
            conversation_id=validated_conversation,
            system_prompt=system_prompt,
        )


class ClearAgentThread:
    """Clears short-term agent checkpoints for one conversation id."""

    def __init__(self, memory: AgentThreadMemory) -> None:
        self._memory = memory

    def execute(self, *, conversation_id: str) -> None:
        """Clear thread memory for ``conversation_id`` (idempotent).

        Raises:
            ApplicationValidationError: ``conversation_id`` fails its contract.
        """
        validated = require_conversation_id(conversation_id)
        self._memory.clear(conversation_id=validated)
