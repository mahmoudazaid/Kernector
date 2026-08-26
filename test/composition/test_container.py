"""Verifies the composition root wires ports to concrete implementations."""

import inspect
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from application.ask_service import AskService
from composition import (
    Settings,
    available_providers,
    build_ask_service,
    build_chat_model,
    build_prompt_repository,
    build_vector_store,
    load_settings,
)
from domain.models import AskResult, Message
from domain.ports import ChatModel, PromptRepository, VectorStore
from infrastructure.llm.ollama import OllamaChat
from infrastructure.llm.openrouter import OpenRouterChat
from infrastructure.vectorstore.chroma import ChromaVectorStore

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


def test_composition_root_boots_without_presentation(tmp_path: Path) -> None:
    """AC: a CLI/API smoke boot wires concrete adapters, importing no UI.

    The vector store is built here too: composition already imports chromadb at
    module level, so it costs no measurable extra time, and a bare process being
    able to build one is #85's precondition (§13).
    """
    code = (
        "import sys\n"
        "import infrastructure.config as config\n"
        # Neutralized before load_settings runs, so the CHROMA_PERSIST_PATH
        # passed in `env` below cannot be overridden by a local .env (§3.1).
        "config.load_dotenv = lambda *a, **k: False\n"
        "from composition import build_chat_model, build_vector_store, load_settings\n"
        "settings = load_settings()\n"
        "model = build_chat_model(settings)\n"
        "assert model is not None, 'no chat model built'\n"
        "store = build_vector_store(settings)\n"
        "assert store is not None, 'no vector store built'\n"
        "assert 'streamlit' not in sys.modules, 'streamlit was imported'\n"
        "leaked = [m for m in sys.modules if m.split('.')[0] == 'presentation']\n"
        "assert not leaked, f'presentation imported: {leaked}'\n"
    )
    store_path = tmp_path / "chroma"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "CHROMA_PERSIST_PATH": str(store_path)},
    )
    assert result.returncode == 0, result.stderr
    assert store_path.is_dir(), "the store was not created under tmp_path"


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


@pytest.fixture
def chroma_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings pointed at `tmp_path`, with `.env` neutralized first.

    `load_settings()` calls `load_dotenv(override=True)`, so without the patch a
    developer's local `.env` would beat `setenv` and these tests would build a
    store inside their real data directory while still passing (§3.1).
    """
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    target = tmp_path / "chroma"
    monkeypatch.setenv("CHROMA_PERSIST_PATH", str(target))
    monkeypatch.setenv("CHROMA_COLLECTION", "kernector_knowledge")

    settings = load_settings()
    # Containment is asserted before anything is constructed, so a misresolved
    # path cannot write outside tmp_path even once (§13).
    assert settings.chroma.persist_path == target
    return settings


def test_build_vector_store_returns_the_chroma_adapter(
    chroma_settings: Settings,
) -> None:
    """AC: composition selects the concrete adapter.

    Concrete-type assertions belong only in composition tests; every other layer
    sees the port.
    """
    assert isinstance(build_vector_store(chroma_settings), ChromaVectorStore)


def test_built_vector_store_satisfies_the_port(chroma_settings: Settings) -> None:
    store = build_vector_store(chroma_settings)
    for name in ("upsert", "search"):
        assert callable(getattr(store, name, None)), name
        assert inspect.signature(getattr(type(store), name)) == inspect.signature(
            getattr(VectorStore, name)
        ), name


def test_build_vector_store_is_annotated_with_the_port() -> None:
    """The builder advertises the abstraction, not the implementation (§10)."""
    assert inspect.signature(build_vector_store).return_annotation is VectorStore


def test_build_vector_store_is_a_pure_factory(chroma_settings: Settings) -> None:
    """No memoization: a settings-keyed cache would retain an open SQLite handle
    to a tmp_path pytest has already deleted, and would force an explicit
    cache_clear fixture here (§10). Holding one instance across Streamlit reruns
    is presentation's concern and #85's decision.
    """
    first = build_vector_store(chroma_settings)
    assert build_vector_store(chroma_settings) is not first


def test_build_vector_store_creates_the_directory_it_was_given(
    chroma_settings: Settings,
) -> None:
    """Configuration must not touch the filesystem; construction must."""
    assert not chroma_settings.chroma.persist_path.exists()
    build_vector_store(chroma_settings)
    assert chroma_settings.chroma.persist_path.is_dir()
