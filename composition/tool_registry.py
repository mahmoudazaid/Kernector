"""Lazy domain-tool pack loading for the composition root."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence

from application.errors import ConfigurationError
from application.invoke_tool import ToolRegistry
from domain.ports import Tool
from infrastructure.config import Settings

# Explicit allowlist: env pack IDs never become unchecked import paths.
SUPPORTED_DOMAIN_TOOL_PACKS: Mapping[str, str] = {
    "software-delivery": "packs.software_delivery.registration:build_tools",
}


def build_tool_registry(settings: Settings) -> ToolRegistry:
    """Build a tool registry from enabled domain tool packs.

    Imports pack registration modules only for configured pack IDs. When no packs
    are enabled, returns an empty registry without importing ``packs``.

    Args:
        settings: Runtime settings including ``domain_tools.enabled_packs``.

    Returns:
        Registry of tools contributed by enabled packs.

    Raises:
        ConfigurationError: Unknown pack ID or invalid registration target.
    """
    tools: list[Tool] = []
    for pack_id in settings.domain_tools.enabled_packs:
        target = SUPPORTED_DOMAIN_TOOL_PACKS.get(pack_id)
        if target is None:
            raise ConfigurationError(
                f"unknown domain tool pack: {pack_id!r}"
            )
        module_name, _, attr = target.partition(":")
        if not module_name or not attr:
            raise ConfigurationError(
                f"invalid domain tool pack target for {pack_id!r}"
            )
        module = importlib.import_module(module_name)
        build_tools = getattr(module, attr)
        contributed: Sequence[Tool] = build_tools()
        tools.extend(contributed)
    return ToolRegistry(tools)
