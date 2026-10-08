"""Registration entrypoint for the Software Delivery domain tool pack."""

from collections.abc import Callable, Sequence

from domain.ports import ArtifactUploader, ChatModel, Tool, XrayTestImporter
from packs.software_delivery.chat_intent import ChatToolSelection, select_chat_intent
from packs.software_delivery.tools.create_xray_tests import (
    TOOL_NAME as CREATE_XRAY_TESTS_TOOL,
)
from packs.software_delivery.tools.create_xray_tests import (
    CreatedRecorder,
    CreateXrayTestsTool,
    DraftLoader,
    XrayMcpBinding,
)
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
    xray_importer: XrayTestImporter | None = None,
    xray_load_draft: DraftLoader | None = None,
    xray_on_created: CreatedRecorder | None = None,
) -> Sequence[Tool]:
    """Return chat-bound tools contributed by this pack.

    Chat registers Drive export and Xray test creation (#199) when their
    collaborators are wired. Retired scaffolding tools (#285) are not revived
    here or on MCP (#320).

    ``chat_model`` is optional until a chat tool that needs an LLM is registered.
    Each tool's collaborators must be provided as an atomic pair (both or
    neither). ``xray_on_created`` optionally records the keys each Xray run
    created for its draft.

    Raises:
        SoftwareDeliveryToolWiringError: Exactly one collaborator of a pair
            was provided.
    """
    _ = chat_model  # reserved for future LLM-backed chat tools
    if (export_render is None) ^ (export_uploader is None):
        raise SoftwareDeliveryToolWiringError(
            "export_render and export_uploader must both be provided"
        )
    if (xray_importer is None) ^ (xray_load_draft is None):
        raise SoftwareDeliveryToolWiringError(
            "xray_importer and xray_load_draft must both be provided"
        )
    tools: list[Tool] = []
    if export_render is not None and export_uploader is not None:
        tools.append(
            ExportTestCasesGoogleDriveTool(
                render=export_render,
                uploader=export_uploader,
            )
        )
    if xray_importer is not None and xray_load_draft is not None:
        tools.append(
            CreateXrayTestsTool(
                load_draft=xray_load_draft,
                importer=xray_importer,
                on_created=xray_on_created,
            )
        )
    return tuple(tools)


def build_mcp_tools(
    *,
    chat_model_factory: Callable[[], ChatModel] | None = None,
    test_design_binding: TestDesignMcpBinding | None = None,
    xray_binding: XrayMcpBinding | None = None,
) -> Sequence[tuple[str, Callable[[], Tool]]]:
    """Return MCP tool factories for this pack (excludes Drive export).

    Test Design tools (#338) are contributed only when composition supplies a
    workspace-bound ``test_design_binding``. Xray test creation (#199) is
    contributed only with an ``xray_binding``; the registry gates it behind
    human approval (ADR 0010). ``chat_model_factory`` is reserved for future
    LLM-backed MCP tools.
    """
    _ = chat_model_factory
    tools: list[tuple[str, Callable[[], Tool]]] = []
    if test_design_binding is not None:
        binding = test_design_binding
        tools.extend(
            (tool_id, lambda tool_cls=tool_cls: tool_cls(binding))
            for tool_id, tool_cls in TEST_DESIGN_MCP_TOOLS
        )
    if xray_binding is not None:
        xray = xray_binding
        tools.append(
            (
                CREATE_XRAY_TESTS_TOOL,
                lambda: CreateXrayTestsTool(
                    load_draft=xray.load_draft,
                    importer=xray.importer,
                    destination_label=xray.project_key,
                    on_created=xray.on_created,
                    args_schema=xray.args_schema,
                    output_schema=xray.output_schema,
                ),
            )
        )
    return tuple(tools)


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
