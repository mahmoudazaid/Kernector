"""Wire the composition-owned MCP tool registry from settings."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping

from application.errors import ConfigurationError
from application.retrieve_knowledge import RetrieveKnowledge
from composition.mcp.project_list import TOOL_NAME as PROJECT_LIST_TOOL
from composition.mcp.project_list import ProjectListTool
from composition.mcp.project_relationships import (
    TOOL_NAME as PROJECT_RELATIONSHIPS_TOOL,
)
from composition.mcp.project_relationships import ProjectRelationshipsTool
from composition.mcp.search_knowledge import TOOL_NAME as SEARCH_KNOWLEDGE_TOOL
from composition.mcp.search_knowledge import SearchKnowledgeTool
from composition.mcp.tool_registry import McpToolContribution, McpToolRegistry
from domain.ports import ChatModel
from infrastructure.config import Settings

# Explicit allowlist: env pack IDs never become unchecked import paths.
SUPPORTED_MCP_TOOL_PACKS: Mapping[str, str] = {
    "software-delivery": "packs.software_delivery.registration:build_mcp_tools",
}

RetrieveProvider = RetrieveKnowledge | Callable[[], RetrieveKnowledge]


def _resolve_retrieve(retrieve: RetrieveProvider) -> RetrieveKnowledge:
    """Accept a retrieve use-case or a lazy factory (catalog / admin paths)."""
    if isinstance(retrieve, RetrieveKnowledge):
        return retrieve
    return retrieve()


def build_mcp_tool_registry(
    settings: Settings,
    *,
    retrieve: RetrieveProvider,
    chat_model_factory: Callable[[], ChatModel] | None = None,
) -> McpToolRegistry:
    """Build the MCP registry with core search + pack MCP factories.

    Pack factories come from allowlisted ``build_mcp_tools`` entrypoints.
    Software Delivery receives a workspace-bound Test Design binding (#338). ``chat_model_factory`` is forwarded for future LLM-backed pack MCP
    tools. Pack modules are imported only when that pack id is in
    ``settings.domain_tools.enabled_packs``.

    ``retrieve`` may be a lazy ``Callable`` so catalog-only callers (Admin tool
    list) never open Chroma until ``core.search_knowledge`` is actually invoked.
    """
    contributions: list[McpToolContribution] = [
        McpToolContribution(
            tool_id=SEARCH_KNOWLEDGE_TOOL,
            pack_id=None,
            factory=lambda: _search_knowledge_tool(settings, retrieve),
        ),
        McpToolContribution(
            tool_id=PROJECT_LIST_TOOL,
            pack_id=None,
            factory=lambda: _project_list_tool(settings),
        ),
        McpToolContribution(
            tool_id=PROJECT_RELATIONSHIPS_TOOL,
            pack_id=None,
            factory=lambda: _project_relationships_tool(settings),
        ),
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
            chat_model_factory=chat_model_factory,
            **_pack_mcp_kwargs(pack_id, settings),
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


def _search_knowledge_tool(
    settings: Settings, retrieve: RetrieveProvider
) -> SearchKnowledgeTool:
    from composition.container import _catalog_workspace_ready

    project_ids_for = None
    descriptor_for = None
    if _catalog_workspace_ready(settings):
        try:
            from application.errors import ConfigurationError
            from composition.artifact.container import build_artifact_index
            from composition.errors import DocumentOperationError
            from composition.project.container import build_resolve_projects_for_source
            from infrastructure.catalog.errors import CatalogError
            from infrastructure.project.sql_store import ProjectStoreError

            resolve = build_resolve_projects_for_source(settings)
            index = build_artifact_index(settings)
            project_ids_for = resolve.execute
            descriptor_for = index.get
        except (
            ConfigurationError,
            DocumentOperationError,
            CatalogError,
            ProjectStoreError,
            OSError,
        ):
            project_ids_for = None
            descriptor_for = None
    return SearchKnowledgeTool(
        _resolve_retrieve(retrieve),
        project_ids_for=project_ids_for,
        descriptor_for=descriptor_for,
    )


def _project_list_tool(settings: Settings) -> ProjectListTool:
    from composition.project.container import build_project_use_cases

    return ProjectListTool(build_project_use_cases(settings).list)


def _project_relationships_tool(settings: Settings) -> ProjectRelationshipsTool:
    from composition.relationship.container import build_list_artifact_relationships

    return ProjectRelationshipsTool(build_list_artifact_relationships(settings))


def _pack_mcp_kwargs(pack_id: str, settings: Settings) -> dict[str, object]:
    """Return pack-specific collaborators for that pack's ``build_mcp_tools``."""
    if pack_id != "software-delivery":
        return {}
    from composition.mcp.test_design import build_mcp_test_design_binding
    from composition.xray_export.mcp import build_mcp_xray_binding
    from composition.xray_export.test_file_create import build_xray_file_create_binding
    from composition.xray_export.test_file_preview import build_mcp_test_file_binding

    from composition.mcp.project_profile import build_mcp_project_profile_binding

    return {
        "test_design_binding": build_mcp_test_design_binding(settings),
        "project_profile_binding": build_mcp_project_profile_binding(settings),
        "xray_binding": build_mcp_xray_binding(settings),
        "test_file_binding": build_mcp_test_file_binding(settings),
        "xray_file_binding": build_xray_file_create_binding(settings),
    }
