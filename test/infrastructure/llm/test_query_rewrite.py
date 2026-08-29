"""OpenRouter query-rewrite adapter, tested through an injected fake model."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from domain.errors import QueryRewriterError
from infrastructure.config import OpenRouterSettings
from infrastructure.llm.query_rewrite import (
    QueryRewriteConfigError,
    OpenRouterQueryRewriter,
    REWRITE_SYSTEM,
)


def _settings(**overrides: object) -> OpenRouterSettings:
    values: dict[str, object] = {
        "api_key": "sk-test",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "chat/model",
        "models": (),
        "embedding_model": "embed/model",
        "rewrite_model": "rewrite/model",
        "timeout": 30.0,
    }
    values.update(overrides)
    return OpenRouterSettings(**values)  # type: ignore[arg-type]


class _FakeModel:
    """Records messages passed to ``invoke`` and returns fixed content."""

    def __init__(
        self,
        content: object = "payment service failure last week",
        *,
        error: BaseException | None = None,
    ) -> None:
        self.messages: object | None = None
        self._content = content
        self._error = error

    def invoke(self, messages: object, **_kwargs: object) -> SimpleNamespace:
        self.messages = messages
        if self._error is not None:
            raise self._error
        return SimpleNamespace(content=self._content)


def test_rewrite_sends_system_and_human_messages_structurally() -> None:
    fake = _FakeModel("rewritten retrieval query")
    rewriter = OpenRouterQueryRewriter(_settings(), model=fake)

    result = rewriter.rewrite("what broke?")

    assert result == "rewritten retrieval query"
    assert isinstance(fake.messages, list)
    assert len(fake.messages) == 2
    system, human = fake.messages
    assert isinstance(system, SystemMessage)
    assert system.content == REWRITE_SYSTEM
    assert isinstance(human, HumanMessage)
    assert human.content == "what broke?"


def test_rewrite_normalizes_surrounding_whitespace() -> None:
    fake = _FakeModel("  payment service failure  \n")
    rewriter = OpenRouterQueryRewriter(_settings(), model=fake)

    assert rewriter.rewrite("vague") == "payment service failure"


def test_invocation_failure_raises_query_rewriter_error() -> None:
    fake = _FakeModel(error=RuntimeError("upstream down"))
    rewriter = OpenRouterQueryRewriter(_settings(), model=fake)

    with pytest.raises(QueryRewriterError, match="upstream down") as raised:
        rewriter.rewrite("what broke?")

    assert isinstance(raised.value.__cause__, RuntimeError)


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_blank_content_raises_query_rewriter_error(blank: str) -> None:
    fake = _FakeModel(blank)
    rewriter = OpenRouterQueryRewriter(_settings(), model=fake)

    with pytest.raises(QueryRewriterError, match="blank"):
        rewriter.rewrite("what broke?")


@pytest.mark.parametrize(
    "content",
    [None, ["payment failure"], {"text": "payment failure"}, 42, object()],
)
def test_non_string_content_raises_query_rewriter_error(content: object) -> None:
    fake = _FakeModel(content)
    rewriter = OpenRouterQueryRewriter(_settings(), model=fake)

    with pytest.raises(QueryRewriterError):
        rewriter.rewrite("what broke?")


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("api_key", None, "OPENROUTER_API_KEY"),
        ("api_key", "", "OPENROUTER_API_KEY"),
        ("base_url", None, "OPENROUTER_BASE_URL"),
        ("base_url", "", "OPENROUTER_BASE_URL"),
        ("rewrite_model", None, "OPENROUTER_REWRITE_MODEL|OPENROUTER_MODEL"),
        ("rewrite_model", "", "OPENROUTER_REWRITE_MODEL|OPENROUTER_MODEL"),
    ],
)
def test_missing_config_raises_at_construction(
    field: str, value: object, match: str
) -> None:
    with pytest.raises(QueryRewriteConfigError, match=match):
        OpenRouterQueryRewriter(_settings(**{field: value}))
