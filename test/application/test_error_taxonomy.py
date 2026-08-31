"""Error taxonomy mapping: ports and adapters raise typed, user-safe errors."""

import pytest

from application.errors import ApplicationValidationError, ConfigurationError
from application.rewrite_and_retrieve import QueryRewriteFailure
from domain.errors import (
    DomainValidationError,
    ProviderError,
    QueryRewriterError,
    ToolFailureError,
    VectorStoreError,
)
from domain.models import Message
from domain.ports import Tool
from infrastructure.config import OllamaSettings, OpenRouterSettings
from infrastructure.embeddings.openrouter import (
    EmbeddingConfigError,
    OpenRouterEmbeddings,
)
from infrastructure.llm.ollama import OllamaChat, OllamaConfigError
from infrastructure.llm.openrouter import ChatConfigError, OpenRouterChat
from infrastructure.llm.query_rewrite import OpenRouterQueryRewriter
from infrastructure.vectorstore.chroma import ChromaStoreError


def _openrouter(**overrides: object) -> OpenRouterSettings:
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


class _RaisingChat:
    def __call__(self, prompt_value: object, **_kwargs: object) -> object:
        raise RuntimeError("vendor body with sk-leaked")


class _ChatFactory:
    def __call__(self, config: object, settings: object) -> _RaisingChat:
        return _RaisingChat()


class _RaisingEmbedClient:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embed vendor detail")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("embed vendor detail")


class _RaisingRewriteModel:
    def invoke(self, messages: object, **_kwargs: object) -> object:
        raise RuntimeError("rewrite vendor detail")


def test_chat_provider_failure_is_provider_error_without_vendor_text() -> None:
    chat = OpenRouterChat(_openrouter(), model_factory=_ChatFactory())

    with pytest.raises(ProviderError) as raised:
        chat.complete("system", (Message(role="user", content="hi"),), {})

    assert "sk-leaked" not in str(raised.value)
    assert raised.value.__cause__ is not None


def test_embedding_provider_failure_is_provider_error_without_vendor_text() -> None:
    embeddings = OpenRouterEmbeddings(_openrouter(), client=_RaisingEmbedClient())

    with pytest.raises(ProviderError) as raised:
        embeddings.embed_query("q")

    assert "embed vendor detail" not in str(raised.value)


def test_query_rewrite_failure_is_provider_error_subclass() -> None:
    rewriter = OpenRouterQueryRewriter(_openrouter(), model=_RaisingRewriteModel())

    with pytest.raises(QueryRewriterError) as raised:
        rewriter.rewrite("what broke?")

    assert isinstance(raised.value, ProviderError)
    assert "rewrite vendor detail" not in str(raised.value)


def test_query_rewrite_failure_application_type_is_provider_error() -> None:
    assert issubclass(QueryRewriteFailure, ProviderError)


def test_chroma_store_error_is_vector_store_error() -> None:
    assert issubclass(ChromaStoreError, VectorStoreError)


def test_config_errors_remain_distinct_from_provider_errors() -> None:
    assert issubclass(ChatConfigError, RuntimeError)
    assert issubclass(OllamaConfigError, RuntimeError)
    assert issubclass(EmbeddingConfigError, RuntimeError)
    assert issubclass(ConfigurationError, RuntimeError)
    assert not issubclass(ConfigurationError, ProviderError)
    assert not issubclass(ProviderError, ConfigurationError)


def test_validation_errors_remain_value_errors() -> None:
    assert issubclass(ApplicationValidationError, ValueError)
    assert issubclass(DomainValidationError, ValueError)


def test_ollama_missing_base_url_is_config_error() -> None:
    with pytest.raises(OllamaConfigError, match="OLLAMA_BASE_URL"):
        OllamaChat(OllamaSettings(base_url=None, model="m", timeout=1.0))


def test_tool_failure_error_is_named_by_tool_port() -> None:
    assert issubclass(ToolFailureError, RuntimeError)
    assert "ToolFailureError" in (Tool.run.__doc__ or "")


def test_empty_retrieval_is_not_an_error_type() -> None:
    """Ticket 'retrieval empty' maps to a normal AskResponse, not an exception."""
    assert not hasattr(
        __import__("domain.errors", fromlist=["*"]), "RetrievalEmptyError"
    )
    assert not hasattr(
        __import__("domain.errors", fromlist=["*"]), "RetrievalError"
    )
