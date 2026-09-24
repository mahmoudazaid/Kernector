"""Wire the composition-owned MCP tool registry from settings."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence

from application.errors import ConfigurationError
from application.retrieve_knowledge import RetrieveKnowledge
from composition.mcp_search_knowledge import TOOL_NAME as SEARCH_KNOWLEDGE_TOOL
from composition.mcp_search_knowledge import SearchKnowledgeTool
from composition.mcp_tool_registry import McpToolContribution, McpToolRegistry
from domain.ports import ChatModel
from infrastructure.config import Settings

# Explicit allowlist: env pack IDs never become unchecked import paths.
SUPPORTED_MCP_TOOL_PACKS: Mapping[str, str] = {
    "software-delivery": "packs.software_delivery.registration:build_mcp_tools",
}


def build_mcp_tool_registry(
    settings: Settings,
    *,
    retrieve: RetrieveKnowledge,
    chat_model_factory: Callable[[], ChatModel] | None = None,
) -> McpToolRegistry:
    """Build the MCP registry with core search + pack MCP factories.

    Pack factories come from allowlisted ``build_mcp_tools`` entrypoints
    (empty until #326/#327). ``chat_model_factory`` is forwarded for future
    LLM-backed pack MCP tools. Pack modules are imported only when that pack
    id is in ``settings.domain_tools.enabled_packs``.
    """
    contributions: list[McpToolContribution] = [
        McpToolContribution(
            tool_id=SEARCH_KNOWLEDGE_TOOL,
            pack_id=None,
            factory=lambda: SearchKnowledgeTool(retrieve),
        )
    ]
    for pack_id in settings.domain_tools.enabled_packs:
        target = SUPPORTED_MCP_TOOL_PACKS.get(pack_id)
        if target is None:
            continue
        module_name, _, attr = target.partition(":")
        if not module_name or not attr:
            raise ConfigurationError(
                f"invalid MCP tool pack target for {pack_id!r}"
            )
        module = importlib.import_module(module_name)
        build_mcp_tools = getattr(module, attr)
        for tool_id, factory in build_mcp_tools(
            chat_model_factory=chat_model_factory
        ):
            contributions.append(
                McpToolContribution(
                    tool_id=tool_id,
                    pack_id=pack_id,
                    factory=factory,
                )
            )
    return McpToolRegistry(
        contributions=contributions,
        enabled_packs=settings.domain_tools.enabled_packs,
    )


def filter_contributions_for_allowlist(
    contributions: Sequence[McpToolContribution],
    allowlist: frozenset[str],
) -> tuple[McpToolContribution, ...]:
    """Return contributions whose ids appear in *allowlist* (optional prefilter)."""
    return tuple(item for item in contributions if item.tool_id in allowlist)
