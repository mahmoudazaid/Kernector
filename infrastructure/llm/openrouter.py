"""OpenRouter chat adapter."""

import time
from collections.abc import Mapping, Sequence
from typing import Protocol

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from domain.errors import ProviderError
from domain.models import AskResult, Message, Usage
from infrastructure.config import OpenRouterSettings


class ChatConfigError(RuntimeError):
    """The chat credentials are missing or unusable.

    Named so the composition root can catch this specific failure narrowly and
    map it to a typed ``ConfigurationError``. Raised only from construction,
    never from ``complete()``.
    """


class _ChatModelFactory(Protocol):
    def __call__(
        self, config: OpenRouterSettings, settings: Mapping[str, object]
    ) -> object: ...


class OpenRouterChat:
    """ChatModel backed by OpenRouter."""

    def __init__(
        self,
        config: OpenRouterSettings,
        *,
        model_factory: _ChatModelFactory | None = None,
    ) -> None:
        _require_chat_config(config)
        self._config = config
        self._model_factory = model_factory or _default_chat_model

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        started = time.perf_counter()
        try:
            chat_model = self._model_factory(self._config, settings)
            chain = _ask_prompt() | chat_model
            ai_message = chain.invoke({
                "system": system,
                "history": _to_provider_messages(messages),
            })
        except Exception as exc:
            raise ProviderError(
                "The OpenRouter chat provider could not be reached."
            ) from exc
        return AskResult(
            content=ai_message.content,
            model=self._config.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage=_to_usage(getattr(ai_message, "usage_metadata", None)),
            settings=dict(settings),
        )


def _default_chat_model(
    config: OpenRouterSettings, settings: Mapping[str, object]
) -> ChatOpenAI:
    return ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout,
        **settings,
    )


def _require_chat_config(config: OpenRouterSettings) -> None:
    """Fail fast when chat credentials or model are absent."""
    if not config.api_key:
        raise ChatConfigError(
            "Missing OPENROUTER_API_KEY. Add it to .env before chatting."
        )
    if not config.base_url:
        raise ChatConfigError(
            "Missing OPENROUTER_BASE_URL. Add it to .env before chatting."
        )
    if not config.model:
        raise ChatConfigError(
            "Missing OPENROUTER_MODEL. Add it to .env before chatting."
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
