"""Process-scoped short-term agent thread memory runtime (#213).

Owns one ``InMemorySaver`` per process when the Software Delivery agent loop
is enabled. Thread keys are ``{workspace_id}:{conversation_id}`` with
``workspace_id`` from trusted server config. Checkpoints are process-local and
lost on restart; durable stores are deferred (#299). Presentation depends on
this composition-facing type — never on LangGraph directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from application.run_tool_agent import ClearAgentThread
from domain.ports import AgentThreadMemory, ToolCallingAgent
from infrastructure.config import Settings


class _NoOpThreadMemory:
    """Idempotent clear when short-term memory is disabled."""

    def clear(self, *, conversation_id: str) -> None:
        del conversation_id


@dataclass(frozen=True, slots=True)
class ShortTermMemoryRuntime:
    """Composition-owned short-term memory handle for ask + clear.

    Attributes:
        enabled (bool): True when agent-loop memory is active.
        workspace_id (str | None): Bound server workspace when enabled.
    """

    enabled: bool
    workspace_id: str | None
    _checkpointer: object | None
    _clear: ClearAgentThread

    @property
    def short_term_memory_enabled(self) -> bool:
        return self.enabled

    def clear_use_case(self) -> ClearAgentThread:
        """Return the clear use case bound to this runtime (may be a no-op)."""
        return self._clear

    def bind_tool_agent(
        self,
        *,
        system_prompt: str,
        model_factory: object,
    ) -> ToolCallingAgent:
        """Build a ``LangGraphToolAgent`` sharing this runtime's checkpointer."""
        from infrastructure.agents.langgraph_tool_agent import LangGraphToolAgent

        if not self.enabled or self._checkpointer is None or self.workspace_id is None:
            return LangGraphToolAgent(
                system_prompt=system_prompt,
                model_factory=model_factory,  # type: ignore[arg-type]
            )
        return LangGraphToolAgent(
            system_prompt=system_prompt,
            model_factory=model_factory,  # type: ignore[arg-type]
            checkpointer=self._checkpointer,  # type: ignore[arg-type]
            workspace_id=self.workspace_id,
        )


def build_short_term_memory_runtime(settings: Settings) -> ShortTermMemoryRuntime:
    """Construct a short-term memory runtime from settings.

    When ``SOFTWARE_DELIVERY_AGENT_LOOP`` is off, returns a disabled runtime
    with a no-op clear (still validates conversation ids in the use case).

    When on and ``DOCUMENT_CATALOG_WORKSPACE_ID`` is valid, creates a fresh
    ``InMemorySaver`` for this runtime instance. Process reuse comes from the
    presentation/composition cache that holds one runtime, not from this
    builder inventing a hidden global.

    When the agent loop is on but the workspace id is absent/invalid, returns a
    disabled runtime instead of raising so core HTTP routes (settings, ask)
    stay available and degrade rather than 500.
    """
    disabled = ShortTermMemoryRuntime(
        enabled=False,
        workspace_id=None,
        _checkpointer=None,
        _clear=ClearAgentThread(_NoOpThreadMemory()),
    )
    if not settings.domain_tools.agent_loop:
        return disabled

    from infrastructure.agents.langgraph_tool_agent import LangGraphThreadMemory
    from infrastructure.catalog.workspace import require_workspace_id
    from langgraph.checkpoint.memory import InMemorySaver

    try:
        workspace_id = require_workspace_id(settings.document_catalog.workspace_id)
    except ValueError:
        return disabled

    checkpointer = InMemorySaver()
    memory: AgentThreadMemory = LangGraphThreadMemory(
        checkpointer=checkpointer,
        workspace_id=workspace_id,
    )
    return ShortTermMemoryRuntime(
        enabled=True,
        workspace_id=workspace_id,
        _checkpointer=checkpointer,
        _clear=ClearAgentThread(memory),
    )


class ShortTermMemoryRuntimeFactory(Protocol):
    """Builds or returns the process short-term memory runtime."""

    def __call__(self, settings: Settings) -> ShortTermMemoryRuntime: ...
