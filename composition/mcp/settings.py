"""Composition facade for MCP settings and registry wiring."""

from __future__ import annotations

from collections.abc import Callable

from application.retrieve_knowledge import RetrieveKnowledge
from composition.mcp.wiring import build_mcp_tool_registry
from composition.mcp.tool_registry import McpToolRegistry
from domain.ports import ChatModel
from infrastructure.config import McpSettings, Settings, require_mcp_settings_from_env


def load_mcp_settings() -> McpSettings:
    """Load fail-closed MCP settings for the presentation adapter."""
    return require_mcp_settings_from_env()


def build_mcp_registry_for_runtime(
    settings: Settings,
    *,
    retrieve: RetrieveKnowledge | None = None,
    chat_model_factory: Callable[[], ChatModel] | None = None,
) -> McpToolRegistry:
    """Wire the MCP registry from runtime settings (lazy ChatModel + retrieve).

    Retrieve/Chroma is deferred until ``core.search_knowledge`` is invoked so
    Admin catalog listing does not contend with a second PersistentClient.
    """
    from composition.container import build_chat_model, build_retrieve_knowledge

    retrieve_holder: list[RetrieveKnowledge | None] = [retrieve]

    def _lazy_retrieve() -> RetrieveKnowledge:
        if retrieve_holder[0] is None:
            retrieve_holder[0] = build_retrieve_knowledge(settings)
        active = retrieve_holder[0]
        assert active is not None
        return active

    def _factory() -> ChatModel:
        if chat_model_factory is not None:
            return chat_model_factory()
        return build_chat_model(settings)

    return build_mcp_tool_registry(
        settings,
        retrieve=retrieve if retrieve is not None else _lazy_retrieve,
        chat_model_factory=_factory,
    )


__all__ = (
    "McpSettings",
    "build_mcp_registry_for_runtime",
    "load_mcp_settings",
)
