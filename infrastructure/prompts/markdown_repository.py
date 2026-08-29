"""Markdown-backed prompt repository."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from domain.models import PromptVariant


class MarkdownPromptRepository:
    """PromptRepository backed by markdown files with frontmatter."""

    def __init__(self, prompt_dirs: Sequence[Path]) -> None:
        self._dirs = tuple(prompt_dirs)
        self._prompts: dict[str, PromptVariant] | None = None
        self._default_key: str | None = None

    def all(self) -> Mapping[str, PromptVariant]:
        self._load()
        return self._prompts

    def default_key(self) -> str:
        self._load()
        return self._default_key

    def _load(self) -> None:
        if self._prompts is not None:
            return

        prompts: dict[str, PromptVariant] = {}
        default_key: str | None = None

        for directory in self._dirs:
            for path in sorted(directory.glob("*.md")):
                meta, body = _parse_prompt_file(path)
                key = meta["key"]

                if key in prompts:
                    raise ValueError(f"Prompt key {key} already exists")

                prompts[key] = PromptVariant(
                    key=key,
                    name=meta["name"],
                    description=meta["description"],
                    system=body,
                    off_topic_marker=meta.get("off_topic_marker"),
                )

                if meta.get("default", "false").lower() == "true":
                    if default_key is not None:
                        raise ValueError("Multiple default prompts found")
                    default_key = key

        if not prompts:
            raise ValueError(
                "No prompts found in " + ", ".join(str(d) for d in self._dirs)
            )
        if default_key is None:
            raise ValueError("No default prompt found")

        self._prompts = prompts
        self._default_key = default_key


def _parse_prompt_file(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8").strip()
    if not text.startswith("---\n"):
        raise ValueError(f"Invalid prompt file: {path.name} frontmatter is missing")

    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Invalid prompt file: {path.name} has invalid frontmatter")

    row_meta = parts[1].strip().splitlines()
    body = parts[2].strip()

    meta: dict[str, str] = {}
    for line in row_meta:
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()

    return meta, body
