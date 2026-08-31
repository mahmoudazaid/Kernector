"""Chroma and knowledge-corpus configuration: defaults, path resolution, validation."""

from pathlib import Path

import pytest

from infrastructure.config import load_settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Neutralize `.env`, which `load_settings()` loads with `override=True`.

    Without this, a local `.env` silently beats `monkeypatch.setenv` and these
    tests would pass while reading a developer's real configuration (§3.1).
    """
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("CHROMA_PERSIST_PATH", raising=False)
    monkeypatch.delenv("CHROMA_COLLECTION", raising=False)
    monkeypatch.delenv("KNOWLEDGE_CORPUS_PATH", raising=False)
    monkeypatch.delenv("DOCUMENT_CATALOG_PATH", raising=False)
    monkeypatch.delenv("PROMPT_PACKS", raising=False)
    monkeypatch.delenv("PROMPT_DEFAULT_KEY", raising=False)
    monkeypatch.delenv("MAX_UPLOAD_BYTES", raising=False)
    return monkeypatch


def test_chroma_defaults(env: pytest.MonkeyPatch) -> None:
    chroma = load_settings().chroma
    assert chroma.persist_path == PROJECT_ROOT / "data" / "chroma"
    assert chroma.collection == "kernector_knowledge"


def test_relative_path_resolves_against_the_repo_root_not_the_cwd(
    env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env.chdir(tmp_path)  # a CWD-relative resolution would land here instead
    env.setenv("CHROMA_PERSIST_PATH", "data/chroma")
    assert load_settings().chroma.persist_path == PROJECT_ROOT / "data" / "chroma"


def test_absolute_path_is_preserved(
    env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "vectors"
    env.setenv("CHROMA_PERSIST_PATH", str(target))
    assert load_settings().chroma.persist_path == target


def test_tilde_is_expanded(env: pytest.MonkeyPatch) -> None:
    env.setenv("CHROMA_PERSIST_PATH", "~/kernector-chroma")
    assert load_settings().chroma.persist_path == Path.home() / "kernector-chroma"


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_blank_collection_is_rejected(env: pytest.MonkeyPatch, raw: str) -> None:
    env.setenv("CHROMA_COLLECTION", raw)
    with pytest.raises(ValueError, match="CHROMA_COLLECTION"):
        load_settings()


def test_loading_settings_creates_no_directories(
    env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Configuration loading must not touch the filesystem (§3)."""
    target = tmp_path / "not-yet-created"
    env.setenv("CHROMA_PERSIST_PATH", str(target))
    assert load_settings().chroma.persist_path == target
    assert not target.exists()


def test_knowledge_corpus_defaults(env: pytest.MonkeyPatch) -> None:
    knowledge = load_settings().knowledge
    assert (
        knowledge.corpus_path
        == PROJECT_ROOT / "data" / "knowledge" / "documents.json"
    )


def test_knowledge_relative_path_resolves_against_repo_root_not_cwd(
    env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env.chdir(tmp_path)
    env.setenv("KNOWLEDGE_CORPUS_PATH", "data/knowledge/documents.json")
    assert (
        load_settings().knowledge.corpus_path
        == PROJECT_ROOT / "data" / "knowledge" / "documents.json"
    )


def test_knowledge_absolute_path_is_preserved(
    env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "custom-corpus.json"
    env.setenv("KNOWLEDGE_CORPUS_PATH", str(target))
    assert load_settings().knowledge.corpus_path == target


def test_knowledge_tilde_is_expanded(env: pytest.MonkeyPatch) -> None:
    env.setenv("KNOWLEDGE_CORPUS_PATH", "~/kernector-corpus.json")
    assert (
        load_settings().knowledge.corpus_path
        == Path.home() / "kernector-corpus.json"
    )


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_blank_knowledge_corpus_path_is_rejected(
    env: pytest.MonkeyPatch, raw: str
) -> None:
    env.setenv("KNOWLEDGE_CORPUS_PATH", raw)
    with pytest.raises(ValueError, match="KNOWLEDGE_CORPUS_PATH"):
        load_settings()


def test_document_catalog_defaults(env: pytest.MonkeyPatch) -> None:
    catalog = load_settings().document_catalog
    assert catalog.path == PROJECT_ROOT / "data" / "catalog" / "uploads.json"


def test_document_catalog_absolute_path_is_preserved(
    env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "uploads.json"
    env.setenv("DOCUMENT_CATALOG_PATH", str(target))
    assert load_settings().document_catalog.path == target


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_blank_document_catalog_path_is_rejected(
    env: pytest.MonkeyPatch, raw: str
) -> None:
    env.setenv("DOCUMENT_CATALOG_PATH", raw)
    with pytest.raises(ValueError, match="DOCUMENT_CATALOG_PATH"):
        load_settings()


def test_prompt_packs_default_to_core(env: pytest.MonkeyPatch) -> None:
    prompts = load_settings().prompts
    assert prompts.pack_paths == (
        PROJECT_ROOT / "prompts" / "packs" / "core",
    )


def test_prompt_packs_resolves_csv_names_under_packs_root(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("PROMPT_PACKS", "alpha, beta")
    assert load_settings().prompts.pack_paths == (
        PROJECT_ROOT / "prompts" / "packs" / "alpha",
        PROJECT_ROOT / "prompts" / "packs" / "beta",
    )


@pytest.mark.parametrize("raw", ["", "   ", ",", " , , "])
def test_prompt_packs_allows_empty_list(
    env: pytest.MonkeyPatch, raw: str
) -> None:
    env.setenv("PROMPT_PACKS", raw)
    assert load_settings().prompts.pack_paths == ()


def test_retrieval_defaults(env: pytest.MonkeyPatch) -> None:
    retrieval = load_settings().retrieval
    assert retrieval.limit == 5
    assert retrieval.relevance_threshold == 0.0


def test_retrieval_settings_are_read_from_env(env: pytest.MonkeyPatch) -> None:
    env.setenv("RETRIEVAL_LIMIT", "12")
    env.setenv("RELEVANCE_THRESHOLD", "0.35")
    retrieval = load_settings().retrieval
    assert retrieval.limit == 12
    assert retrieval.relevance_threshold == 0.35


@pytest.mark.parametrize("raw", ["0", "-1"])
def test_non_positive_retrieval_limit_is_rejected(
    env: pytest.MonkeyPatch, raw: str
) -> None:
    env.setenv("RETRIEVAL_LIMIT", raw)
    with pytest.raises(ValueError, match="RETRIEVAL_LIMIT must be > 0"):
        load_settings()


def test_non_integer_retrieval_limit_is_rejected(env: pytest.MonkeyPatch) -> None:
    env.setenv("RETRIEVAL_LIMIT", "many")
    with pytest.raises(ValueError, match="RETRIEVAL_LIMIT must be an integer"):
        load_settings()


@pytest.mark.parametrize("raw", ["0", "-1"])
def test_non_positive_max_input_length_is_rejected(
    env: pytest.MonkeyPatch, raw: str
) -> None:
    env.setenv("MAX_INPUT_LENGTH", raw)
    with pytest.raises(ValueError, match="MAX_INPUT_LENGTH must be > 0"):
        load_settings()


def test_non_integer_max_input_length_is_rejected(env: pytest.MonkeyPatch) -> None:
    env.setenv("MAX_INPUT_LENGTH", "abc")
    with pytest.raises(ValueError, match="MAX_INPUT_LENGTH must be an integer"):
        load_settings()


def test_max_upload_bytes_default(env: pytest.MonkeyPatch) -> None:
    assert load_settings().max_upload_bytes == 5 * 1024 * 1024


def test_max_upload_bytes_is_read_from_env(env: pytest.MonkeyPatch) -> None:
    env.setenv("MAX_UPLOAD_BYTES", "1048576")
    assert load_settings().max_upload_bytes == 1_048_576


@pytest.mark.parametrize("raw", ["0", "-1"])
def test_non_positive_max_upload_bytes_is_rejected(
    env: pytest.MonkeyPatch, raw: str
) -> None:
    env.setenv("MAX_UPLOAD_BYTES", raw)
    with pytest.raises(ValueError, match="MAX_UPLOAD_BYTES must be > 0"):
        load_settings()


def test_non_integer_max_upload_bytes_is_rejected(env: pytest.MonkeyPatch) -> None:
    env.setenv("MAX_UPLOAD_BYTES", "big")
    with pytest.raises(ValueError, match="MAX_UPLOAD_BYTES must be an integer"):
        load_settings()


@pytest.mark.parametrize("raw", ["1.01", "-1.01", "42"])
def test_out_of_range_relevance_threshold_is_rejected(
    env: pytest.MonkeyPatch, raw: str
) -> None:
    """The threshold is a cosine similarity, so it shares the port's [-1, 1]
    range. A value outside it silently disables or blanks the evidence filter."""
    env.setenv("RELEVANCE_THRESHOLD", raw)
    with pytest.raises(ValueError, match=r"RELEVANCE_THRESHOLD must be within"):
        load_settings()


def test_non_numeric_relevance_threshold_is_rejected(env: pytest.MonkeyPatch) -> None:
    env.setenv("RELEVANCE_THRESHOLD", "close-enough")
    with pytest.raises(ValueError, match="RELEVANCE_THRESHOLD must be a number"):
        load_settings()


def test_prompt_default_key_unset_is_none(env: pytest.MonkeyPatch) -> None:
    assert load_settings().prompts.default_key is None


def test_prompt_default_key_is_read_from_env(env: pytest.MonkeyPatch) -> None:
    env.setenv("PROMPT_DEFAULT_KEY", "knowledge_qa")
    assert load_settings().prompts.default_key == "knowledge_qa"


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_blank_prompt_default_key_is_rejected(
    env: pytest.MonkeyPatch, raw: str
) -> None:
    env.setenv("PROMPT_DEFAULT_KEY", raw)
    with pytest.raises(ValueError, match="PROMPT_DEFAULT_KEY"):
        load_settings()


def test_rewrite_model_uses_dedicated_env_when_set(env: pytest.MonkeyPatch) -> None:
    env.setenv("OPENROUTER_MODEL", "chat/model")
    env.setenv("OPENROUTER_REWRITE_MODEL", "rewrite/model")
    assert load_settings().openrouter.rewrite_model == "rewrite/model"


def test_rewrite_model_falls_back_to_openrouter_model(
    env: pytest.MonkeyPatch,
) -> None:
    env.delenv("OPENROUTER_REWRITE_MODEL", raising=False)
    env.setenv("OPENROUTER_MODEL", "chat/model")
    assert load_settings().openrouter.rewrite_model == "chat/model"


def test_rewrite_model_is_none_when_both_unset(env: pytest.MonkeyPatch) -> None:
    env.delenv("OPENROUTER_REWRITE_MODEL", raising=False)
    env.delenv("OPENROUTER_MODEL", raising=False)
    assert load_settings().openrouter.rewrite_model is None
