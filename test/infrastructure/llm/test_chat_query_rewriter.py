"""Shared chat-backed QueryRewriter conformance (#462)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from openai import AuthenticationError

from domain.errors import ProviderAuthError, ProviderError, QueryRewriterError
from infrastructure.llm.chat_query_rewriter import ChatQueryRewriter


class _FakeModel:
    def __init__(
        self, content: object = "rewritten query", *, error: BaseException | None = None
    ) -> None:
        self._content = content
        self._error = error

    def invoke(self, messages: object, **kwargs: object) -> Any:
        if self._error is not None:
            raise self._error
        return type("Msg", (), {"content": self._content})()


def test_rewrite_returns_normalized_text() -> None:
    rewriter = ChatQueryRewriter(_FakeModel("  retrieval query  "))
    assert rewriter.rewrite("what is it?") == "retrieval query"


def test_blank_content_raises_query_rewriter_error() -> None:
    rewriter = ChatQueryRewriter(_FakeModel("   "))
    with pytest.raises(QueryRewriterError, match="blank"):
        rewriter.rewrite("q")


def test_non_string_content_raises_query_rewriter_error() -> None:
    rewriter = ChatQueryRewriter(_FakeModel(42))
    with pytest.raises(QueryRewriterError, match="non-string"):
        rewriter.rewrite("q")


def test_list_content_blocks_are_flattened() -> None:
    rewriter = ChatQueryRewriter(
        _FakeModel([{"type": "text", "text": "retrieval "}, {"type": "text", "text": "query"}])
    )
    assert rewriter.rewrite("what is it?") == "retrieval query"


def test_typed_provider_error_is_re_raised_unchanged() -> None:
    from domain.errors import ProviderTimeoutError

    upstream = ProviderTimeoutError("The query rewrite provider timed out.")
    rewriter = ChatQueryRewriter(_FakeModel(error=upstream))
    with pytest.raises(ProviderTimeoutError) as raised:
        rewriter.rewrite("q")
    assert raised.value is upstream


def test_invocation_failure_is_typed_and_sanitized() -> None:
    upstream = AuthenticationError(
        "bad key sk-secret",
        response=httpx.Response(401, request=httpx.Request("POST", "https://example")),
        body={"error": {"message": "sk-secret"}},
    )
    rewriter = ChatQueryRewriter(_FakeModel(error=upstream))
    with pytest.raises(ProviderAuthError) as raised:
        rewriter.rewrite("q")
    assert "sk-secret" not in str(raised.value)
    assert "sk-secret" not in repr(raised.value)
    assert raised.value.__cause__ is None
    assert not isinstance(raised.value, QueryRewriterError)


def test_generic_invocation_failure_is_provider_error() -> None:
    rewriter = ChatQueryRewriter(_FakeModel(error=RuntimeError("upstream sk-secret")))
    with pytest.raises(ProviderError) as raised:
        rewriter.rewrite("q")
    assert "sk-secret" not in str(raised.value)
    assert raised.value.__cause__ is None
