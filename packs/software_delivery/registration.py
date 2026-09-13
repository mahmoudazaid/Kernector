"""Registration entrypoint for the Software Delivery domain tool pack."""

from collections.abc import Callable, Sequence

from domain.ports import ChatModel, Tool
from packs.software_delivery.chat_intent import ChatToolSelection, select_chat_intent
from packs.software_delivery.orchestration import (
    OpaqueInvoke,
    OrchestrateSoftwareDelivery,
)

SelectChatIntent = Callable[[str], ChatToolSelection | None]


def build_tools(*, chat_model: ChatModel) -> Sequence[Tool]:
    """Return tools contributed by this pack.

    The three scaffolding tools (risk score, generate test cases, export
    markdown) are retired. Future tools land under ``tools/`` and are
    returned from this function without further structure churn.

    ``chat_model`` remains required so the registry contract stays stable
    for the next real tool that needs a chat collaborator.
    """
    _ = chat_model  # required by registry contract; unused while empty
    return ()


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
