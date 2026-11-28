"""Anthropic chat adapter (#462). Embeddings are not advertised for Anthropic."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Protocol

from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from domain.errors import ProviderError
from domain.models import AskResult, Message, Usage
from infrastructure.config import AnthropicSettings
from infrastructure.llm.provider_failures import classify_provider_failure

_CONNECTION_FAILURE_MESSAGE = "The Anthropic chat provider could not be reached."
_PARSE_FAILURE_MESSAGE = "The Anthropic chat response could not be parsed."


class ChatConfigError(RuntimeError):
    """Anthropic chat credentials or model are missing or unusable."""


class _ChatModelFactory(Protocol):
    def __call__(
        self, config: AnthropicSettings, settings: Mapping[str, object]
    ) -> object: ...


class AnthropicChat:
    """ChatModel backed by Anthropic."""

    def __init__(
        self,
        config: AnthropicSettings,
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
            raise classify_provider_failure(
                exc, fallback_message=_CONNECTION_FAILURE_MESSAGE
            ) from None

        try:
            content = _normalize_content(getattr(ai_message, "content", None))
            if not content.strip():
                raise TypeError("chat content must be a non-empty str")
            usage = _to_usage(getattr(ai_message, "usage_metadata", None))
            return AskResult(
                content=content,
                model=self._config.model,
                latency_ms=int((time.perf_counter() - started) * 1000),
                usage=usage,
                settings=dict(settings),
            )
        except Exception:
            raise ProviderError(_PARSE_FAILURE_MESSAGE) from None


def _default_chat_model(
    config: AnthropicSettings, settings: Mapping[str, object]
) -> ChatAnthropic:
    return ChatAnthropic(
        model=config.model,
        api_key=config.api_key,
        timeout=config.timeout,
        **settings,
    )


def _require_chat_config(config: AnthropicSettings) -> None:
    if not config.api_key:
        raise ChatConfigError(
            "Missing ANTHROPIC_API_KEY. Add it to .env before chatting."
        )
    if not config.model:
        raise ChatConfigError(
            "Missing ANTHROPIC_MODEL. Add it to .env before chatting."
        )


def _ask_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([
        ("system", "{system}"),
        MessagesPlaceholder("history"),
    ])


def _to_provider_messages(messages: Sequence[Message]) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in messages]


def _normalize_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif hasattr(block, "text") and isinstance(block.text, str):
                parts.append(block.text)
        return "".join(parts)
    raise TypeError(f"chat content must be a non-empty str, got {content!r}")


def _to_usage(meta: object) -> Usage | None:
    if meta is None:
        return None
    if not isinstance(meta, Mapping):
        raise TypeError(f"usage_metadata must be a mapping, got {type(meta).__name__}")
    return Usage(
        prompt_tokens=meta.get("input_tokens"),
        completion_tokens=meta.get("output_tokens"),
        total_tokens=meta.get("total_tokens"),
        cost=meta.get("cost"),
    )
