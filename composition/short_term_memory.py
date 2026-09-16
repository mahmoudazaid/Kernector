"""Process-scoped short-term agent thread memory runtime (#213 / #214).

Owns one ``InMemorySaver`` per process when the Software Delivery agent loop
is enabled. Thread keys are ``{workspace_id}:{conversation_id}`` with
``workspace_id`` from trusted server config. Checkpoints and pending tool
approvals are process-local and lost on restart; durable stores are deferred.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from application.decide_tool_approval import DecideToolApproval
from application.run_tool_agent import ClearAgentThread
from domain.tool_approval import ToolApprovalDecisionLedger, ToolApprovalPolicy
from domain.ports import AgentThreadMemory, ToolCallingAgent
from infrastructure.config import Settings

logger = logging.getLogger(__name__)


class _NoOpThreadMemory:
    """Idempotent clear when short-term memory is disabled."""

    def clear(self, *, conversation_id: str) -> None:
        del conversation_id


@dataclass
class ShortTermMemoryRuntime:
    """Composition-owned short-term memory handle for ask + clear + HITL."""

    enabled: bool
    workspace_id: str | None
    _checkpointer: object | None
    _clear: ClearAgentThread
    _pending_args: dict = field(default_factory=dict)
    _approval_ledger: ToolApprovalDecisionLedger = field(
        default_factory=ToolApprovalDecisionLedger
    )
    _approval_policy: ToolApprovalPolicy = field(
        default_factory=lambda: ToolApprovalPolicy()
    )
    _bound_agent: object | None = field(default=None, repr=False)

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
            agent = LangGraphToolAgent(
                system_prompt=system_prompt,
                model_factory=model_factory,  # type: ignore[arg-type]
                approval_policy=self._approval_policy,
                pending_args=self._pending_args,
            )
            self._bound_agent = agent
            return agent
        agent = LangGraphToolAgent(
            system_prompt=system_prompt,
            model_factory=model_factory,  # type: ignore[arg-type]
            checkpointer=self._checkpointer,  # type: ignore[arg-type]
            workspace_id=self.workspace_id,
            approval_policy=self._approval_policy,
            pending_args=self._pending_args,
        )
        self._bound_agent = agent
        return agent

    def decide_tool_approval(self) -> DecideToolApproval:
        """Return the HITL resume use case bound to the last bound agent."""
        agent = self._bound_agent
        if agent is None:
            from infrastructure.agents.langgraph_tool_agent import LangGraphToolAgent

            agent = LangGraphToolAgent(
                system_prompt="system",
                checkpointer=self._checkpointer,  # type: ignore[arg-type]
                workspace_id=self.workspace_id,
                approval_policy=self._approval_policy,
                pending_args=self._pending_args,
            )
            self._bound_agent = agent
        return DecideToolApproval(resumer=agent, ledger=self._approval_ledger)


def build_short_term_memory_runtime(settings: Settings) -> ShortTermMemoryRuntime:
    """Construct a short-term memory runtime from settings."""
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
    except ValueError as error:
        logger.warning("Short-term memory disabled: %s", error)
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
