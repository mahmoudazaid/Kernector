"""OpenRouter chat adapter."""

import time
from collections.abc import Mapping, Sequence

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from domain.models import AskResult, Message, Usage
from infrastructure.config import OpenRouterSettings


class OpenRouterChat:
    """ChatModel backed by OpenRouter."""

    def __init__(self, config: OpenRouterSettings) -> None:
        self._config = config

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        started = time.perf_counter()
        try:
            chat_model = ChatOpenAI(
                model=self._config.model,
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                timeout=self._config.timeout,
                **settings,
            )
            chain = _ask_prompt() | chat_model
            ai_message = chain.invoke({
                "system": system,
                "history": _to_provider_messages(messages),
            })
        except Exception:
            return AskResult(
                content="Failed to connect to OpenRouter",
                model=self._config.model,
                settings=dict(settings),
            )
        return AskResult(
            content=ai_message.content,
            model=self._config.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage=_to_usage(getattr(ai_message, "usage_metadata", None)),
            settings=dict(settings),
        )


def _ask_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([
        ("system", "{system}"),
        MessagesPlaceholder("history"),
    ])


def _to_provider_messages(messages: Sequence[Message]) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in messages]


def _to_usage(meta: Mapping[str, object] | None) -> Usage | None:
    if not meta:
        return None
    return Usage(
        prompt_tokens=meta.get("input_tokens"),
        completion_tokens=meta.get("output_tokens"),
        total_tokens=meta.get("total_tokens"),
        cost=meta.get("cost"),
    )
