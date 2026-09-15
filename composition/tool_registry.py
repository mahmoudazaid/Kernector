"""Lazy domain-tool pack loading for the composition root."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence

from application.errors import ConfigurationError
from application.invoke_tool import ToolRegistry
from domain.ports import ArtifactUploader, ChatModel, Tool
from infrastructure.config import Settings

# Explicit allowlist: env pack IDs never become unchecked import paths.
SUPPORTED_DOMAIN_TOOL_PACKS: Mapping[str, str] = {
    "software-delivery": "packs.software_delivery.registration:build_tools",
}

ExportRender = Callable[[str, Sequence[str]], str]


def enabled_domain_tool_packs(settings: Settings) -> tuple[str, ...]:
    """Return configured pack IDs that this build supports.

    Filters unknown IDs as a response-projection rule so clients only see
    packs the current build can advertise. Preserves configured order.
    Unknown packs still fail at tool-registry construction time.

    Args:
        settings: Runtime settings including ``domain_tools.enabled_packs``.

    Returns:
        Supported pack IDs in configured order; empty when none are enabled.
    """
    return tuple(
        pack_id
        for pack_id in settings.domain_tools.enabled_packs
        if pack_id in SUPPORTED_DOMAIN_TOOL_PACKS
    )


def build_tool_registry(
    settings: Settings,
    *,
    chat_model: ChatModel | None = None,
    export_render: ExportRender | None = None,
    export_uploader: ArtifactUploader | None = None,
) -> ToolRegistry:
    """Build a tool registry from enabled domain tool packs.

    Imports pack registration modules only for configured pack IDs. When no packs
    are enabled, returns an empty registry without importing ``packs``.

    For Software Delivery Drive export, ``export_render`` and ``export_uploader``
    must be supplied together (atomic pair). ``chat_model`` is optional while the
    pack only contributes deterministic tools.

    Args:
        settings: Runtime settings including ``domain_tools.enabled_packs``.
        chat_model: Optional chat collaborator for future LLM-backed tools.
        export_render: Composition #305 adapter for titles-only export.
        export_uploader: Bound Google Drive ``ArtifactUploader``.

    Returns:
        Registry of tools contributed by enabled packs.

    Raises:
        ConfigurationError: Unknown pack ID, invalid registration target, or
            partial export collaborator wiring.
    """
    if (export_render is None) ^ (export_uploader is None):
        raise ConfigurationError(
            "export_render and export_uploader must both be provided"
        )
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
        if pack_id == "software-delivery":
            try:
                contributed: Sequence[Tool] = build_tools(
                    chat_model=chat_model,
                    export_render=export_render,
                    export_uploader=export_uploader,
                )
            except ValueError as exc:
                raise ConfigurationError(str(exc)) from exc
        else:
            contributed = build_tools()
        tools.extend(contributed)
    return ToolRegistry(tools)
