"""Verifies the composition root wires ports to concrete implementations."""

import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from application.ask_service import AskService
from composition import (
    available_providers,
    build_ask_service,
    build_chat_model,
    build_prompt_repository,
    load_settings,
)
from domain.models import AskResult, Message
from domain.ports import ChatModel, PromptRepository
from infrastructure.llm.ollama import OllamaChat
from infrastructure.llm.openrouter import OpenRouterChat

REPO_ROOT = Path(__file__).resolve().parents[2]


class _StubChat:
    """A ChatModel that records what it was asked, so injection is observable."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Message, ...]]] = []

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        self.calls.append((system, tuple(messages)))
        return AskResult(content="stubbed")


def test_composition_root_boots_without_presentation() -> None:
    """AC: a CLI/API smoke boot wires concrete adapters, importing no UI."""
    code = (
        "import sys\n"
        "from composition import build_chat_model, load_settings\n"
        "model = build_chat_model(load_settings())\n"
        "assert model is not None, 'no chat model built'\n"
        "assert 'streamlit' not in sys.modules, 'streamlit was imported'\n"
        "leaked = [m for m in sys.modules if m.split('.')[0] == 'presentation']\n"
        "assert not leaked, f'presentation imported: {leaked}'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "provider,expected",
    [("openrouter", OpenRouterChat), ("ollama", OllamaChat)],
)
def test_build_chat_model_returns_the_provider_implementation(
    provider: str, expected: type
) -> None:
    settings = load_settings()
    model = build_chat_model(settings, provider=provider, base_url="http://h:11434")
    assert isinstance(model, expected)


def test_every_advertised_provider_is_buildable() -> None:
    """`available_providers()` must not advertise a factory that does not work."""
    settings = load_settings()
    for provider in available_providers():
        assert build_chat_model(
            settings, provider=provider, base_url="http://h:11434"
        ) is not None


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        build_chat_model(load_settings(), provider="gpt-by-carrier-pigeon")


def test_runtime_overrides_reach_the_adapter() -> None:
    settings = load_settings()
    model = build_chat_model(
        settings, provider="ollama", model="llama3.2", base_url="http://elsewhere:1234/"
    )
    assert model._config.model == "llama3.2"
    assert model._base_url == "http://elsewhere:1234"


def test_runtime_overrides_do_not_mutate_the_loaded_settings() -> None:
    """Overrides must not leak from one request into the next."""
    settings = load_settings()
    original = settings.ollama
    build_chat_model(settings, provider="ollama", model="scratch", base_url="http://x")
    assert settings.ollama == original


def test_ask_service_receives_its_collaborator() -> None:
    """AC: collaborators are injected, not imported as globals."""
    stub = _StubChat()
    service: AskService = build_ask_service(stub)

    result = service.ask("system prompt", "hello")

    assert result.content == "stubbed"
    assert stub.calls == [("system prompt", (Message(role="user", content="hello"),))]


def test_prompt_repository_satisfies_its_port() -> None:
    repository: PromptRepository = build_prompt_repository()
    prompts = repository.all()
    assert prompts, "no prompt variants loaded"
    assert repository.default_key() in prompts


def test_built_chat_models_satisfy_the_port() -> None:
    settings = load_settings()
    model: ChatModel = build_chat_model(settings, provider="openrouter")
    assert callable(model.complete)
