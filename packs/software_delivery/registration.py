"""Registration entrypoint for the Software Delivery domain tool pack."""

from collections.abc import Callable, Sequence

from domain.ports import ChatModel, Tool
from packs.software_delivery.chat_intent import ChatToolSelection, select_chat_intent
from packs.software_delivery.export_test_cases_markdown_tool import (
    ExportTestCasesMarkdownTool,
)
from packs.software_delivery.generate_test_cases_tool import GenerateTestCasesTool
from packs.software_delivery.orchestration import (
    OpaqueInvoke,
    OrchestrateSoftwareDelivery,
)
from packs.software_delivery.risk_score_tool import RiskScoreTool

SelectChatIntent = Callable[[str], ChatToolSelection | None]


def build_tools(*, chat_model: ChatModel) -> Sequence[Tool]:
    """Return tools contributed by this pack."""
    return (
        RiskScoreTool(),
        GenerateTestCasesTool(chat_model),
        ExportTestCasesMarkdownTool(),
    )


def build_orchestrator(*, invoke: OpaqueInvoke) -> OrchestrateSoftwareDelivery:
    """Return the pack orchestration use case wired to opaque invoke."""
    return OrchestrateSoftwareDelivery(invoke)


def build_chat_intent_selector() -> SelectChatIntent:
    """Return the pack's chat-time intent policy.

    Takes no collaborators: the policy is a pure function of the query. It is
    exposed here anyway so composition keeps reaching this pack through exactly
    one module.
    """
    return select_chat_intent
