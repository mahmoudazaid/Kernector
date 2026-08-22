"""Ask use case: build the conversation and delegate to a chat model."""

from collections.abc import Mapping, Sequence

from domain.model_settings import SETTINGS
from domain.models import AskResult, Message
from domain.ports import ChatModel


class AskService:
    """Orchestrates a single ask against whichever chat model it was given."""

    def __init__(self, chat_model: ChatModel) -> None:
        self._chat_model = chat_model

    def ask(
        self,
        system: str,
        user_text: str,
        settings: Mapping[str, object] | None = None,
        history: Sequence[Message] = (),
    ) -> AskResult:
        conversation = [*history, Message(role="user", content=user_text)]
        return self._chat_model.complete(system, conversation, _allowed(settings))


def _allowed(settings: Mapping[str, object] | None) -> dict[str, object]:
    """Keep only settings the domain recognises, so adapters get clean kwargs."""
    valid_keys = {s.key for s in SETTINGS}
    return {k: v for k, v in (settings or {}).items() if k in valid_keys}
