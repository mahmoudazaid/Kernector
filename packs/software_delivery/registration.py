"""Registration entrypoint for the Software Delivery domain tool pack."""

from collections.abc import Callable, Sequence

from domain.ports import ArtifactUploader, ChatModel, Tool
from packs.software_delivery.chat_intent import ChatToolSelection, select_chat_intent
from packs.software_delivery.tools.export_test_cases_google_drive import (
    ExportTestCasesGoogleDriveTool,
    RenderExportMarkdown,
)
from packs.software_delivery.tools.test_design_mcp import (
    TEST_DESIGN_MCP_TOOLS,
    TestDesignMcpBinding,
)

SelectChatIntent = Callable[[str], ChatToolSelection | None]


class SoftwareDeliveryToolWiringError(ValueError):
    """Pack registration received an incomplete collaborator set."""


def build_tools(
    *,
    chat_model: ChatModel | None = None,
    export_render: RenderExportMarkdown | None = None,
    export_uploader: ArtifactUploader | None = None,
) -> Sequence[Tool]:
    """Return chat-bound tools contributed by this pack.

    Chat registration stays Drive-only when collaborators are wired.
    Retired scaffolding tools (#285) are not revived here or on MCP (#320);
    live pack tools land via follow-ups (#326/#327) through
    :func:`build_mcp_tools`.

    ``chat_model`` is optional until a chat tool that needs an LLM is registered.
    Drive export collaborators must be provided as an atomic pair (both or
    neither).

    Raises:
        SoftwareDeliveryToolWiringError: Exactly one of the export
            collaborators was provided.
    """
    _ = chat_model  # reserved for future LLM-backed chat tools
    if (export_render is None) ^ (export_uploader is None):
        raise SoftwareDeliveryToolWiringError(
            "export_render and export_uploader must both be provided"
        )
    tools: list[Tool] = []
    if export_render is not None and export_uploader is not None:
        tools.append(
            ExportTestCasesGoogleDriveTool(
                render=export_render,
                uploader=export_uploader,
            )
        )
    return tuple(tools)


def build_mcp_tools(
    *,
    chat_model_factory: Callable[[], ChatModel] | None = None,
    test_design_binding: TestDesignMcpBinding | None = None,
) -> Sequence[tuple[str, Callable[[], Tool]]]:
    """Return MCP tool factories for this pack (excludes Drive export).

    Test Design tools (#338) are contributed only when composition supplies a
    workspace-bound ``test_design_binding``; otherwise the result is empty.
    ``chat_model_factory`` is reserved for future LLM-backed MCP tools.
    """
    _ = chat_model_factory
    if test_design_binding is None:
        return ()
    binding = test_design_binding
    return tuple(
        (tool_id, lambda tool_cls=tool_cls: tool_cls(binding))
        for tool_id, tool_cls in TEST_DESIGN_MCP_TOOLS
    )


def build_chat_intent_selector(
    *,
    export_intent_enabled: bool = False,
) -> SelectChatIntent:
    """Return the pack's chat-time intent policy.

    ``export_intent_enabled`` must track ``SOFTWARE_DELIVERY_AGENT_LOOP``. When
    False, the selector always returns ``None``: only the agent path can run
    a Drive export.
    """
    if not export_intent_enabled:
        return lambda _query: None
    return select_chat_intent
