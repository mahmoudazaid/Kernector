"""MarkdownPromptRepository: pack-directory loading and merge semantics."""

from pathlib import Path

import pytest

from infrastructure.prompts.markdown_repository import MarkdownPromptRepository


def _write_prompt(
    directory: Path,
    *,
    filename: str,
    key: str,
    name: str = "Test Prompt",
    description: str = "A test prompt.",
    default: bool = False,
    off_topic_marker: str | None = None,
    body: str = "You are a helpful assistant.",
) -> Path:
    lines = [
        "---",
        f"key: {key}",
        f"name: {name}",
        f"description: {description}",
    ]
    if default:
        lines.append("default: true")
    if off_topic_marker is not None:
        lines.append(f"off_topic_marker: {off_topic_marker}")
    lines.extend(["---", "", body, ""])
    path = directory / filename
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_loads_prompts_from_configured_directories(tmp_path: Path) -> None:
    pack = tmp_path / "pack-a"
    pack.mkdir()
    _write_prompt(pack, filename="alpha.md", key="alpha", default=True, body="Alpha system.")

    repository = MarkdownPromptRepository((pack,))

    prompts = repository.all()
    assert set(prompts) == {"alpha"}
    assert prompts["alpha"].system == "Alpha system."
    assert repository.default_key() == "alpha"


def test_merges_prompts_from_multiple_directories(tmp_path: Path) -> None:
    pack_a = tmp_path / "pack-a"
    pack_b = tmp_path / "pack-b"
    pack_a.mkdir()
    pack_b.mkdir()
    _write_prompt(pack_a, filename="alpha.md", key="alpha", default=True)
    _write_prompt(pack_b, filename="beta.md", key="beta", name="Beta")

    repository = MarkdownPromptRepository((pack_a, pack_b))

    assert set(repository.all()) == {"alpha", "beta"}
    assert repository.default_key() == "alpha"


def test_ignores_empty_directory_when_another_has_prompts(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    pack = tmp_path / "pack"
    empty.mkdir()
    pack.mkdir()
    _write_prompt(pack, filename="alpha.md", key="alpha", default=True)

    repository = MarkdownPromptRepository((empty, pack))

    assert set(repository.all()) == {"alpha"}
    assert repository.default_key() == "alpha"


def test_empty_pack_paths_yield_no_prompts_and_no_default() -> None:
    repository = MarkdownPromptRepository(())

    assert repository.all() == {}
    assert repository.default_key() is None


def test_empty_directories_yield_no_prompts_and_no_default(tmp_path: Path) -> None:
    empty_a = tmp_path / "empty-a"
    empty_b = tmp_path / "empty-b"
    empty_a.mkdir()
    empty_b.mkdir()

    repository = MarkdownPromptRepository((empty_a, empty_b))

    assert repository.all() == {}
    assert repository.default_key() is None


def test_rejects_duplicate_prompt_keys_across_directories(tmp_path: Path) -> None:
    pack_a = tmp_path / "pack-a"
    pack_b = tmp_path / "pack-b"
    pack_a.mkdir()
    pack_b.mkdir()
    _write_prompt(pack_a, filename="alpha.md", key="shared", default=True)
    _write_prompt(pack_b, filename="other.md", key="shared", name="Other")

    repository = MarkdownPromptRepository((pack_a, pack_b))

    with pytest.raises(ValueError, match="already exists"):
        repository.all()


def test_rejects_multiple_defaults_across_directories(tmp_path: Path) -> None:
    pack_a = tmp_path / "pack-a"
    pack_b = tmp_path / "pack-b"
    pack_a.mkdir()
    pack_b.mkdir()
    _write_prompt(pack_a, filename="alpha.md", key="alpha", default=True)
    _write_prompt(pack_b, filename="beta.md", key="beta", default=True)

    repository = MarkdownPromptRepository((pack_a, pack_b))

    with pytest.raises(ValueError, match="Multiple default"):
        repository.all()


def test_default_key_override_wins_over_frontmatter(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    _write_prompt(pack, filename="alpha.md", key="alpha", default=True)
    _write_prompt(pack, filename="beta.md", key="beta", name="Beta")

    repository = MarkdownPromptRepository((pack,), default_key="beta")

    assert repository.default_key() == "beta"


def test_default_key_override_rejects_unknown_key(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    _write_prompt(pack, filename="alpha.md", key="alpha", default=True)

    repository = MarkdownPromptRepository((pack,), default_key="missing")

    with pytest.raises(ValueError, match="missing"):
        repository.all()


def test_default_key_override_allows_multiple_frontmatter_defaults(
    tmp_path: Path,
) -> None:
    pack_a = tmp_path / "pack-a"
    pack_b = tmp_path / "pack-b"
    pack_a.mkdir()
    pack_b.mkdir()
    _write_prompt(pack_a, filename="alpha.md", key="alpha", default=True)
    _write_prompt(pack_b, filename="beta.md", key="beta", default=True)

    repository = MarkdownPromptRepository(
        (pack_a, pack_b), default_key="beta"
    )

    assert set(repository.all()) == {"alpha", "beta"}
    assert repository.default_key() == "beta"


def test_default_key_override_allows_missing_frontmatter_default(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    _write_prompt(pack, filename="alpha.md", key="alpha", default=False)

    repository = MarkdownPromptRepository((pack,), default_key="alpha")

    assert repository.default_key() == "alpha"


def test_missing_default_yields_none_default_key(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    _write_prompt(pack, filename="alpha.md", key="alpha", default=False)

    repository = MarkdownPromptRepository((pack,))

    assert set(repository.all()) == {"alpha"}
    assert repository.default_key() is None


def test_preserves_off_topic_marker_from_frontmatter(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    _write_prompt(
        pack,
        filename="alpha.md",
        key="alpha",
        default=True,
        off_topic_marker="## Not Relevant",
    )

    repository = MarkdownPromptRepository((pack,))

    assert repository.all()["alpha"].off_topic_marker == "## Not Relevant"
