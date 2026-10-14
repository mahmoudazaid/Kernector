"""Registration entrypoint for the Software Delivery domain tool pack."""

from collections.abc import Callable, Sequence
from typing import Protocol

from domain.ports import ArtifactUploader, ChatModel, Tool, XrayTestImporter
from packs.software_delivery.chat_intent import ChatToolSelection, select_chat_intent
from packs.software_delivery.project.contexts import SoftwareDeliveryContextVocabulary
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.tools.create_xray_tests import (
    TOOL_NAME as CREATE_XRAY_TESTS_TOOL,
)
from packs.software_delivery.tools.create_xray_tests import (
    CreatedRecorder,
    CreateXrayTestsTool,
    DraftLoader,
    XrayMcpBinding,
)
from packs.software_delivery.tools.create_xray_tests_from_files import (
    TOOL_NAME as CREATE_XRAY_TESTS_FROM_FILES_TOOL,
)
from packs.software_delivery.tools.create_xray_tests_from_files import (
    XrayFileCreateBinding,
    build_from_binding,
)
from packs.software_delivery.tools.export_test_cases_google_drive import (
    ExportTestCasesGoogleDriveTool,
    RenderExportMarkdown,
)
from packs.software_delivery.tools.preview_test_file_scenarios import (
    TOOL_NAME as PREVIEW_TEST_FILE_SCENARIOS_TOOL,
)
from packs.software_delivery.tools.preview_test_file_scenarios import (
    PreviewTestFileScenariosTool,
    TestFilePreviewMcpBinding,
)
from packs.software_delivery.tools.xray_target import TOOL_NAME as XRAY_TARGET_TOOL
from packs.software_delivery.tools.xray_target import XrayTargetTool
from packs.software_delivery.tools.update_xray_tests_from_files import (
    TOOL_NAME as UPDATE_XRAY_TESTS_FROM_FILES_TOOL,
)
from packs.software_delivery.tools.update_xray_tests_from_files import (
    XrayFileUpdateBinding,
    build_update_from_binding,
)
from packs.software_delivery.tools.test_design_mcp import (
    TEST_DESIGN_MCP_TOOLS,
    TestDesignMcpBinding,
)

SelectChatIntent = Callable[[str], ChatToolSelection | None]


class XrayFileBinding(XrayFileCreateBinding, XrayFileUpdateBinding, Protocol):
    """One composition binding serves creating (#397) and updating (#398) from files."""


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
    test_file_tags: TestFileTagConfig | None = None,
    xray_file_binding: XrayFileBinding | None = None,
) -> Sequence[Tool]:
    """Return chat-bound tools contributed by this pack.

    Chat registers Drive export and Xray test creation (#199) when their
    collaborators are wired, the read-only test file preview (#396)
    when ``test_file_tags`` is supplied, and Xray test creation from files
    (#397) and updates from files (#398) with an ``xray_file_binding``. Retired scaffolding tools (#285) are not revived
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
    if test_file_tags is not None:
        tools.append(PreviewTestFileScenariosTool(test_file_tags))
    if xray_file_binding is not None:
        tools.append(build_from_binding(xray_file_binding))
        tools.append(build_update_from_binding(xray_file_binding))
        tools.append(_xray_target(xray_file_binding))
    return tuple(tools)


def build_mcp_tools(
    *,
    chat_model_factory: Callable[[], ChatModel] | None = None,
    test_design_binding: TestDesignMcpBinding | None = None,
    xray_binding: XrayMcpBinding | None = None,
    test_file_binding: TestFilePreviewMcpBinding | None = None,
    xray_file_binding: XrayFileBinding | None = None,
) -> Sequence[tuple[str, Callable[[], Tool]]]:
    """Return MCP tool factories for this pack (excludes Drive export).

    Test Design tools (#338) are contributed only when composition supplies a
    workspace-bound ``test_design_binding``. Xray test creation (#199) is
    contributed only with an ``xray_binding``; the registry gates it behind
    human approval (ADR 0010). The read-only test file preview (#396) is
    contributed with a ``test_file_binding`` and needs no approval. Xray test
    creation (#397) and update (#398) from files need an ``xray_file_binding``
    and approval.
    ``chat_model_factory`` is reserved for future LLM-backed MCP tools.
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
    if test_file_binding is not None:
        preview = test_file_binding
        tools.append(
            (
                PREVIEW_TEST_FILE_SCENARIOS_TOOL,
                lambda: PreviewTestFileScenariosTool(
                    preview.tags,
                    args_schema=preview.args_schema,
                    output_schema=preview.output_schema,
                    mcp_prompt=preview.mcp_prompt,
                ),
            )
        )
    if xray_file_binding is not None:
        file_binding = xray_file_binding
        tools.append(
            (CREATE_XRAY_TESTS_FROM_FILES_TOOL, lambda: build_from_binding(file_binding))
        )
        tools.append(
            (
                UPDATE_XRAY_TESTS_FROM_FILES_TOOL,
                lambda: build_update_from_binding(file_binding),
            )
        )
        tools.append((XRAY_TARGET_TOOL, lambda: _xray_target(file_binding)))
    return tuple(tools)


def _xray_target(binding: XrayFileBinding) -> XrayTargetTool:
    return XrayTargetTool(
        importer=binding.importer,
        destination_label=binding.destination_label,
        args_schema=binding.target_args_schema,
        output_schema=binding.target_output_schema,
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


def build_context_vocabulary() -> SoftwareDeliveryContextVocabulary:
    """Return the project contexts this pack registers (ADR 0011 section 10)."""
    return SoftwareDeliveryContextVocabulary()
