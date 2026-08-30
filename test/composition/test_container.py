"""Verifies the composition root wires ports to concrete implementations."""

import inspect
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from application.ask_service import AskService
from application.errors import ConfigurationError
from application.ingest_knowledge import IngestKnowledge
from application.retrieve_knowledge import RetrieveKnowledge
from application.rewrite_and_retrieve import RewriteAndRetrieveKnowledge
from composition import (
    KnowledgeLoadError,
    Settings,
    available_providers,
    build_ask_service,
    build_chat_model,
    build_ingest_knowledge,
    build_prompt_repository,
    build_retrieve_knowledge,
    build_rewrite_and_retrieve_knowledge,
    build_vector_store,
    load_knowledge_documents,
    load_runtime_settings,
)
from domain.knowledge import SourceType
from domain.models import AskResult, Message
from domain.ports import ChatModel, PromptRepository, VectorStore
from infrastructure.config import load_settings
from infrastructure.embeddings.openrouter import OpenRouterEmbeddings
from infrastructure.knowledge.corpus import CorpusLoadError
from infrastructure.llm.ollama import OllamaChat
from infrastructure.llm.openrouter import OpenRouterChat
from infrastructure.llm.query_rewrite import OpenRouterQueryRewriter
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
        # Neutralized before load_runtime_settings runs, so the CHROMA_PERSIST_PATH
        # passed in `env` below cannot be overridden by a local .env (§3.1).
        "config.load_dotenv = lambda *a, **k: False\n"
        "from composition import build_chat_model, build_vector_store, load_runtime_settings\n"
        "settings = load_runtime_settings()\n"
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
        env={
            **os.environ,
            "CHROMA_PERSIST_PATH": str(store_path),
            "OPENROUTER_API_KEY": "test-key",
            "OPENROUTER_BASE_URL": "https://openrouter.test/api/v1",
            "OPENROUTER_MODEL": "test/chat-model",
        },
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


def test_prompt_repository_allows_zero_packs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("PROMPT_PACKS", "")
    monkeypatch.delenv("PROMPT_DEFAULT_KEY", raising=False)
    repository: PromptRepository = build_prompt_repository(load_settings())
    assert repository.all() == {}
    assert repository.default_key() is None


def test_build_ask_knowledge_wires_with_zero_packs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from application.ask_knowledge import AskKnowledge
    from composition import build_ask_knowledge

    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("PROMPT_PACKS", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.test/api/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/chat-model")
    monkeypatch.setenv("OPENROUTER_EMBEDDING_MODEL", "test/embedding-model")
    settings = load_settings()
    ask = build_ask_knowledge(settings, chat_model=_StubChat())
    assert isinstance(ask, AskKnowledge)


def test_build_ask_knowledge_wires_configured_retrieval_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from composition import build_ask_knowledge

    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("PROMPT_PACKS", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.test/api/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/chat-model")
    monkeypatch.setenv("OPENROUTER_EMBEDDING_MODEL", "test/embedding-model")
    monkeypatch.setenv("RETRIEVAL_LIMIT", "9")
    monkeypatch.setenv("RELEVANCE_THRESHOLD", "0.42")

    ask = build_ask_knowledge(load_settings(), chat_model=_StubChat())

    assert ask._default_retrieval_limit == 9
    assert ask._relevance_threshold == 0.42


def test_build_ask_knowledge_routes_generation_through_ask_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The settings allowlist lives in AskService; wiring a bare ChatModel into
    AskKnowledge would silently reintroduce a second copy of it."""
    from application.ask_service import AskService
    from composition import build_ask_knowledge

    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("PROMPT_PACKS", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.test/api/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/chat-model")
    monkeypatch.setenv("OPENROUTER_EMBEDDING_MODEL", "test/embedding-model")

    ask = build_ask_knowledge(load_settings(), chat_model=_StubChat())

    assert isinstance(ask._ask_service, AskService)


def test_prompt_repository_satisfies_its_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("PROMPT_PACKS", raising=False)
    monkeypatch.delenv("PROMPT_DEFAULT_KEY", raising=False)
    repository: PromptRepository = build_prompt_repository(load_settings())
    prompts = repository.all()
    assert set(prompts) == {"knowledge_qa"}
    assert repository.default_key() == "knowledge_qa"
    assert "role_qa" not in prompts


def test_build_prompt_repository_uses_settings_pack_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    pack = tmp_path / "custom-pack"
    pack.mkdir()
    (pack / "only.md").write_text(
        "---\n"
        "key: only_key\n"
        "name: Only\n"
        "description: Custom pack prompt.\n"
        "default: true\n"
        "---\n"
        "\n"
        "Custom system.\n",
        encoding="utf-8",
    )
    base = load_settings()
    settings = replace(base, prompts=replace(base.prompts, pack_paths=(pack,)))

    repository = build_prompt_repository(settings)

    assert set(repository.all()) == {"only_key"}
    assert repository.default_key() == "only_key"


def test_build_prompt_repository_wires_default_key_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    pack = tmp_path / "custom-pack"
    pack.mkdir()
    (pack / "alpha.md").write_text(
        "---\n"
        "key: alpha\n"
        "name: Alpha\n"
        "description: Frontmatter default.\n"
        "default: true\n"
        "---\n"
        "\n"
        "Alpha.\n",
        encoding="utf-8",
    )
    (pack / "beta.md").write_text(
        "---\n"
        "key: beta\n"
        "name: Beta\n"
        "description: Override target.\n"
        "---\n"
        "\n"
        "Beta.\n",
        encoding="utf-8",
    )
    base = load_settings()
    settings = replace(
        base,
        prompts=replace(base.prompts, pack_paths=(pack,), default_key="beta"),
    )

    repository = build_prompt_repository(settings)

    assert repository.default_key() == "beta"


def test_build_prompt_repository_rejects_unknown_default_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    pack = tmp_path / "custom-pack"
    pack.mkdir()
    (pack / "only.md").write_text(
        "---\n"
        "key: only_key\n"
        "name: Only\n"
        "description: Custom pack prompt.\n"
        "default: true\n"
        "---\n"
        "\n"
        "Custom system.\n",
        encoding="utf-8",
    )
    base = load_settings()
    settings = replace(
        base,
        prompts=replace(base.prompts, pack_paths=(pack,), default_key="missing"),
    )

    repository = build_prompt_repository(settings)

    with pytest.raises(ValueError, match="missing"):
        repository.all()


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
    for name in ("upsert", "search", "delete_source"):
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


@pytest.fixture
def embedding_env(chroma_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """`chroma_settings` with the embedding credentials guaranteed present.

    `chroma_settings` already neutralized `.env`, which means a developer whose
    key lives only there would otherwise see this fixture's settings come back
    with `api_key=None` (§3.1).
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.test/api/v1")
    monkeypatch.setenv("OPENROUTER_EMBEDDING_MODEL", "test/embedding-model")
    monkeypatch.setenv("CHUNK_SIZE", "400")
    monkeypatch.setenv("CHUNK_OVERLAP", "40")
    return load_settings()


def test_build_ingest_knowledge_wires_the_configured_primitives(
    embedding_env: Settings,
) -> None:
    """AC: the use case receives ports and primitive settings, not config objects."""
    use_case = build_ingest_knowledge(embedding_env)

    assert isinstance(use_case, IngestKnowledge)
    assert use_case._chunk_size == 400
    assert use_case._chunk_overlap == 40
    assert isinstance(use_case._vector_store, ChromaVectorStore)
    assert isinstance(use_case._embedding_model, OpenRouterEmbeddings)


def test_build_ingest_knowledge_is_a_pure_factory(embedding_env: Settings) -> None:
    """A fresh instance per call, matching `build_vector_store`."""
    first = build_ingest_knowledge(embedding_env)
    assert build_ingest_knowledge(embedding_env) is not first


def test_build_retrieve_knowledge_wires_embedding_and_vector_store(
    embedding_env: Settings,
) -> None:
    use_case = build_retrieve_knowledge(embedding_env)

    assert isinstance(use_case, RetrieveKnowledge)
    assert isinstance(use_case._vector_store, ChromaVectorStore)
    assert isinstance(use_case._embedding_model, OpenRouterEmbeddings)


def test_build_retrieve_knowledge_reuses_an_injected_vector_store(
    embedding_env: Settings,
) -> None:
    store = build_vector_store(embedding_env)
    use_case = build_retrieve_knowledge(embedding_env, vector_store=store)
    assert use_case._vector_store is store


def test_build_retrieve_knowledge_is_a_pure_factory(embedding_env: Settings) -> None:
    first = build_retrieve_knowledge(embedding_env)
    assert build_retrieve_knowledge(embedding_env) is not first


@pytest.fixture
def rewrite_env(embedding_env: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Embedding credentials plus a chat/rewrite model name."""
    monkeypatch.setenv("OPENROUTER_MODEL", "test/chat-model")
    return load_settings()


def test_build_rewrite_and_retrieve_knowledge_wires_rewriter_and_retrieve(
    rewrite_env: Settings,
) -> None:
    use_case = build_rewrite_and_retrieve_knowledge(rewrite_env)

    assert isinstance(use_case, RewriteAndRetrieveKnowledge)
    assert isinstance(use_case._query_rewriter, OpenRouterQueryRewriter)
    assert isinstance(use_case._retrieve, RetrieveKnowledge)
    assert isinstance(use_case._retrieve._vector_store, ChromaVectorStore)
    assert isinstance(use_case._retrieve._embedding_model, OpenRouterEmbeddings)


def test_build_rewrite_and_retrieve_knowledge_reuses_an_injected_vector_store(
    rewrite_env: Settings,
) -> None:
    store = build_vector_store(rewrite_env)
    use_case = build_rewrite_and_retrieve_knowledge(
        rewrite_env, vector_store=store
    )
    assert use_case._retrieve._vector_store is store


def test_build_rewrite_and_retrieve_knowledge_is_a_pure_factory(
    rewrite_env: Settings,
) -> None:
    first = build_rewrite_and_retrieve_knowledge(rewrite_env)
    assert build_rewrite_and_retrieve_knowledge(rewrite_env) is not first


def test_missing_rewrite_configuration_surfaces_as_configuration_error(
    chroma_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.test/api/v1")
    monkeypatch.delenv("OPENROUTER_REWRITE_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    settings = load_settings()
    assert settings.openrouter.rewrite_model is None

    with pytest.raises(ConfigurationError, match="OPENROUTER_REWRITE_MODEL|OPENROUTER_MODEL"):
        build_rewrite_and_retrieve_knowledge(settings)


def test_missing_embedding_configuration_on_rewrite_path_surfaces_as_configuration_error(
    chroma_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.test/api/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/chat-model")
    monkeypatch.delenv("OPENROUTER_EMBEDDING_MODEL", raising=False)
    # embedding_model has a hard-coded default; wipe it via replace after load
    settings = load_settings()
    settings = replace(
        settings,
        openrouter=replace(settings.openrouter, embedding_model=""),
    )

    with pytest.raises(ConfigurationError, match="OPENROUTER_EMBEDDING_MODEL"):
        build_rewrite_and_retrieve_knowledge(settings)


def test_missing_embedding_configuration_surfaces_as_configuration_error(
    chroma_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC 2: an absent key is an environment failure with a typed error.

    `chroma_settings` patched `load_dotenv` to a no-op *before* this deletes the
    variable. Without that ordering a local `.env` would restore the key and
    this test would pass vacuously (§3.1).
    """
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = load_settings()
    assert settings.openrouter.api_key is None

    with pytest.raises(ConfigurationError, match="OPENROUTER_API_KEY"):
        build_ingest_knowledge(settings)


def test_missing_chat_configuration_surfaces_as_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent OpenRouter chat credentials fail at build_chat_model, typed."""
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = load_settings()
    assert settings.openrouter.api_key is None

    with pytest.raises(ConfigurationError, match="OPENROUTER_API_KEY"):
        build_chat_model(settings, provider="openrouter")


def test_a_configuration_error_is_not_a_validation_error() -> None:
    """An environment failure is not a contract violation (§ error handling)."""
    assert issubclass(ConfigurationError, RuntimeError)
    assert not issubclass(ConfigurationError, ValueError)


def test_load_runtime_settings_returns_settings_for_composition_factories(
    chroma_settings: Settings,
) -> None:
    """Presentation obtains settings only through the composition seam."""
    settings = load_runtime_settings()

    assert isinstance(settings, Settings)
    assert settings.chroma.persist_path == chroma_settings.chroma.persist_path
    assert build_vector_store(settings) is not None


def test_load_runtime_settings_maps_value_error_to_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expected config parse failures become ConfigurationError for the CLI."""
    monkeypatch.setattr(
        "composition.container.load_settings",
        lambda: (_ for _ in ()).throw(ValueError("CHUNK_SIZE must be an integer")),
    )

    with pytest.raises(ConfigurationError, match="CHUNK_SIZE must be an integer") as exc_info:
        load_runtime_settings()

    assert isinstance(exc_info.value.__cause__, ValueError)


def test_load_knowledge_documents_returns_normalized_source_documents(
    chroma_settings: Settings, tmp_path: Path
) -> None:
    """Composition loads any doc_type without restricting categories."""
    corpus = tmp_path / "corpus.json"
    corpus.write_text(
        json.dumps(
            [
                {
                    "source_id": "adr-001",
                    "title": "Dependency direction",
                    "doc_type": "architecture_decision",
                    "content": "Presentation depends on composition and application.",
                    "status": "approved",
                    "version": "1.0",
                }
            ]
        ),
        encoding="utf-8",
    )
    settings = replace(
        chroma_settings,
        knowledge=replace(chroma_settings.knowledge, corpus_path=corpus),
    )

    documents = load_knowledge_documents(settings)

    assert isinstance(documents, tuple)
    assert len(documents) == 1
    document = documents[0]
    assert document.source_id == "adr-001"
    assert document.metadata.extra["doc_type"] == "architecture_decision"
    assert document.reference.source_type == SourceType.KNOWLEDGE_DOCUMENT


def test_load_knowledge_documents_maps_corpus_failure_to_knowledge_load_error(
    chroma_settings: Settings, tmp_path: Path
) -> None:
    """Missing or unreadable corpus becomes KnowledgeLoadError for the CLI."""
    missing = tmp_path / "absent" / "corpus.json"
    settings = replace(
        chroma_settings,
        knowledge=replace(chroma_settings.knowledge, corpus_path=missing),
    )

    with pytest.raises(KnowledgeLoadError, match=str(missing)) as exc_info:
        load_knowledge_documents(settings)

    assert isinstance(exc_info.value.__cause__, CorpusLoadError)
