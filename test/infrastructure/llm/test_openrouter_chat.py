"""OpenRouter chat adapter, tested through an injected model factory."""

from collections.abc import Mapping

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

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
