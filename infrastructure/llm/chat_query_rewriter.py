"""Chat-backed QueryRewriter shared across chat-capable providers (#462)."""

from __future__ import annotations

from typing import Any, Protocol

from domain.errors import QueryRewriterError
from infrastructure.llm.provider_failures import classify_provider_failure
from infrastructure.llm.query_rewrite import REWRITE_SYSTEM

_INVOKE_FAILURE_MESSAGE = "The query rewrite provider could not be reached."


class _InvocableModel(Protocol):
    def invoke(self, messages: object, **kwargs: object) -> Any: ...


class ChatQueryRewriter:
    """``QueryRewriter`` that invokes an injected chat-compatible model.

    Composition builds provider-specific invocables; this adapter owns rewrite
    semantics and sanitized failure mapping without vendor SDKs.
    """

    def __init__(self, model: _InvocableModel, *, system: str = REWRITE_SYSTEM) -> None:
        self._model = model
        self._system = system

    def rewrite(self, query: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=self._system),
            HumanMessage(content=query),
        ]
        try:
            result = self._model.invoke(messages)
        except Exception as error:
            raise classify_provider_failure(
                error, fallback_message=_INVOKE_FAILURE_MESSAGE
            ) from None

        content = getattr(result, "content", result)
        if not isinstance(content, str):
            raise QueryRewriterError(
                f"Query rewrite returned non-string content: {type(content).__name__}"
            )
        normalized = content.strip()
        if not normalized:
            raise QueryRewriterError("Query rewrite returned a blank retrieval query")
        return normalized
