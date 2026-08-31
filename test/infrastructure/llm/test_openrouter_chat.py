"""OpenRouter chat adapter, tested through an injected model factory."""

from collections.abc import Mapping

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from domain.errors import ProviderError
from domain.models import Message, Usage
from infrastructure.config import OpenRouterSettings
from infrastructure.llm.openrouter import ChatConfigError, OpenRouterChat


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


class _FakeChat:
    """Callable, so LangChain's ``|`` coerces it to a RunnableLambda."""

    def __init__(
        self,
        message: AIMessage | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.prompt_value: object | None = None
        self._message = message
        self._error = error

    def __call__(self, prompt_value: object, **_kwargs: object) -> AIMessage:
        self.prompt_value = prompt_value
        if self._error is not None:
            raise self._error
        assert self._message is not None
        return self._message


class _RecordingFactory:
    """Records the config and per-call settings the adapter builds with."""

    def __init__(self, chat: _FakeChat) -> None:
        self.settings: Mapping[str, object] | None = None
        self._chat = chat

    def __call__(
        self, config: OpenRouterSettings, settings: Mapping[str, object]
    ) -> _FakeChat:
        self.settings = settings
        return self._chat


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("api_key", None, "OPENROUTER_API_KEY"),
        ("api_key", "", "OPENROUTER_API_KEY"),
        ("base_url", None, "OPENROUTER_BASE_URL"),
        ("base_url", "", "OPENROUTER_BASE_URL"),
        ("model", None, "OPENROUTER_MODEL"),
        ("model", "", "OPENROUTER_MODEL"),
    ],
)
def test_missing_config_raises_at_construction(
    field: str, value: object, match: str
) -> None:
    with pytest.raises(ChatConfigError, match=match):
        OpenRouterChat(_settings(**{field: value}))


def test_complete_returns_ask_result_from_injected_model() -> None:
    ai_message = AIMessage(
        content="Answer from context.",
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
        },
    )
    fake = _FakeChat(ai_message)
    factory = _RecordingFactory(fake)
    chat = OpenRouterChat(_settings(), model_factory=factory)
    settings = {"temperature": 0.2, "max_tokens": 256}
    history = (
        Message(role="user", content="What is Kernector?"),
        Message(role="assistant", content="A RAG assistant."),
    )

    result = chat.complete(
        "You answer from context.",
        history,
        settings,
    )

    assert result.content == "Answer from context."
    assert result.model == "chat/model"
    assert result.usage == Usage(
        prompt_tokens=10,
        completion_tokens=4,
        total_tokens=14,
        cost=None,
    )
    assert factory.settings == settings

    assert fake.prompt_value is not None
    messages = fake.prompt_value.to_messages()
    assert len(messages) == 3
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == "You answer from context."
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == "What is Kernector?"
    assert isinstance(messages[2], AIMessage)
    assert messages[2].content == "A RAG assistant."


def test_complete_raises_provider_error_without_vendor_text() -> None:
    upstream = RuntimeError("upstream down")
    fake = _FakeChat(error=upstream)
    chat = OpenRouterChat(_settings(), model_factory=_RecordingFactory(fake))

    with pytest.raises(ProviderError, match="OpenRouter chat provider") as raised:
        chat.complete("system", (Message(role="user", content="hi"),), {})

    assert "upstream down" not in str(raised.value)
    assert raised.value.__cause__ is upstream


@pytest.mark.parametrize(
    "content",
    [None, "", "   ", 42, ["chunk"], {"text": "x"}],
)
def test_complete_raises_parse_error_for_missing_or_non_string_content(
    content: object,
) -> None:
    fake = _FakeChat(AIMessage(content=content))  # type: ignore[arg-type]
    chat = OpenRouterChat(_settings(), model_factory=_RecordingFactory(fake))

    with pytest.raises(
        ProviderError, match="OpenRouter chat response could not be parsed"
    ) as raised:
        chat.complete("system", (Message(role="user", content="hi"),), {})

    assert "chunk" not in str(raised.value)
    assert raised.value.__cause__ is not None


def test_complete_raises_parse_error_for_malformed_usage_metadata() -> None:
    class _BadMeta:
        """Not a mapping — accessing .get must not leak into the user message."""

        def __str__(self) -> str:
            return "usage-secret-token"

    fake = _FakeChat(
        AIMessage(content="ok", usage_metadata=_BadMeta())  # type: ignore[arg-type]
    )
    chat = OpenRouterChat(_settings(), model_factory=_RecordingFactory(fake))

    with pytest.raises(
        ProviderError, match="OpenRouter chat response could not be parsed"
    ) as raised:
        chat.complete("system", (Message(role="user", content="hi"),), {})

    assert "usage-secret-token" not in str(raised.value)
    assert raised.value.__cause__ is not None


def test_complete_raises_parse_error_when_ask_result_construction_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeChat(AIMessage(content="Answer from context."))
    chat = OpenRouterChat(_settings(), model_factory=_RecordingFactory(fake))

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise TypeError("AskResult rejected provider payload: secret-body")

    monkeypatch.setattr(
        "infrastructure.llm.openrouter.AskResult",
        _boom,
    )

    with pytest.raises(
        ProviderError, match="OpenRouter chat response could not be parsed"
    ) as raised:
        chat.complete("system", (Message(role="user", content="hi"),), {})

    assert "secret-body" not in str(raised.value)
    assert isinstance(raised.value.__cause__, TypeError)
