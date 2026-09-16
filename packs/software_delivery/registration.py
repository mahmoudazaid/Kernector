"""Registration entrypoint for the Software Delivery domain tool pack."""

from collections.abc import Callable, Sequence

from domain.ports import ArtifactUploader, ChatModel, Tool
from packs.software_delivery.chat_intent import ChatToolSelection, select_chat_intent
from packs.software_delivery.orchestration import (
    OpaqueInvoke,
    OrchestrateSoftwareDelivery,
)
from packs.software_delivery.tools.export_test_cases_google_drive import (
    ExportTestCasesGoogleDriveTool,
    RenderExportMarkdown,
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
    """Return tools contributed by this pack.

    ``chat_model`` is optional until a tool that needs an LLM is registered.
    Drive export collaborators must be provided as an atomic pair (both or
    neither).

    Raises:
        SoftwareDeliveryToolWiringError: Exactly one of the export
            collaborators was provided.
    """
    _ = chat_model  # reserved for future LLM-backed tools
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


def build_orchestrator(*, invoke: OpaqueInvoke) -> OrchestrateSoftwareDelivery:
    """Return the pack orchestration use case wired to opaque invoke."""
    return OrchestrateSoftwareDelivery(invoke)


def build_chat_intent_selector(
    *,
    export_intent_enabled: bool = False,
) -> SelectChatIntent:
    """Return the pack's chat-time intent policy.

    ``export_intent_enabled`` must track ``SOFTWARE_DELIVERY_AGENT_LOOP``. When
    False, the selector always returns ``None`` so export phrasing cannot revive
    the retired scaffolding chain.
    """
    if not export_intent_enabled:
        return lambda _query: None
    return select_chat_intent
