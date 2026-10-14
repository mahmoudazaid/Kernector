"""Propose target paths for pulled Xray scenarios (#400)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from domain.test_management.xray import StoryNamingContext
from packs.software_delivery.test_files.from_xray import PullFormat
from packs.software_delivery.test_files.models import ParsedTestFile

_ALLOWED_PLACEHOLDERS = frozenset(
    {"{epic_key}", "{epic_summary}", "{story_key}", "{story_summary}"}
)
_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")
_UNSAFE = re.compile(r"[/\\]|^\.\.($|[.\s])|[<>:\"|?*\x00-\x1f]")


@dataclass(frozen=True, slots=True)
class TargetHit:
    kind: Literal["existing", "new"]
    path: str


@dataclass(frozen=True, slots=True)
class TargetAmbiguous:
    paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TargetNamingFailed:
    reason: str


def propose_target(
    *,
    story_key: str,
    fmt: PullFormat,
    inventory: Sequence[ParsedTestFile],
    naming: StoryNamingContext,
    template: str,
    proposed_paths: Mapping[str, str] | None = None,
) -> TargetHit | TargetAmbiguous | TargetNamingFailed:
    """Pick an existing suite/feature for ``story_key`` or a new relative path."""
    extension = ".robot" if fmt == "robot" else ".feature"
    matches = [
        parsed.path
        for parsed in inventory
        if _format_of(parsed) == fmt and _file_story(parsed) == story_key
    ]
    if len(matches) > 1:
        return TargetAmbiguous(tuple(matches))
    if len(matches) == 1:
        return TargetHit("existing", matches[0])
    built = build_new_path(naming, template, extension)
    if isinstance(built, TargetNamingFailed):
        return built
    claimed = set(proposed_paths.values()) if proposed_paths else set()
    inventory_paths = {parsed.path for parsed in inventory}
    if built in inventory_paths or built in claimed:
        return TargetNamingFailed("path_collision")
    return TargetHit("new", built)


def build_new_path(
    naming: StoryNamingContext, template: str, extension: str
) -> str | TargetNamingFailed:
    if naming.epic_presence == "failed":
        return TargetNamingFailed("epic_lookup_failed")
    unknown = _PLACEHOLDER.findall(template)
    if any(token not in _ALLOWED_PLACEHOLDERS for token in unknown):
        return TargetNamingFailed("unknown_template_placeholder")
    values = {
        "epic_key": naming.epic_key or "",
        "epic_summary": naming.epic_summary or "",
        "story_key": naming.story_key,
        "story_summary": naming.story_summary,
    }
    raw = template
    for key, value in values.items():
        raw = raw.replace(f"{{{key}}}", value)
    raw = _collapse_separators(raw)
    basename = _sanitize(raw)
    if not basename:
        basename = _sanitize(naming.story_key) or "story"
    if _UNSAFE.search(basename) or "/" in basename or "\\" in basename or ".." in basename:
        return TargetNamingFailed("path_traversal")
    if basename.endswith(extension):
        return basename
    return f"{basename}{extension}"


def validate_template(template: str) -> str | None:
    """Return a reason code when ``template`` is invalid, else ``None``."""
    unknown = [t for t in _PLACEHOLDER.findall(template) if t not in _ALLOWED_PLACEHOLDERS]
    return "unknown_template_placeholder" if unknown else None


def validate_relative_path(path: str, *, extension: str | None = None) -> str | TargetNamingFailed:
    """Accept a caller-chosen relative path; reject traversal and empty names."""
    value = path.strip().replace("\\", "/")
    if not value or value.startswith("/") or ":" in value.split("/")[0]:
        return TargetNamingFailed("path_traversal")
    parts = [part for part in value.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return TargetNamingFailed("path_traversal")
    if any(_UNSAFE.search(part) for part in parts):
        return TargetNamingFailed("path_traversal")
    joined = "/".join(parts)
    if extension and not joined.endswith(extension):
        joined = f"{joined}{extension}"
    return joined


def _file_story(parsed: ParsedTestFile) -> str | None:
    if parsed.story_key:
        return parsed.story_key
    for scenario in parsed.scenarios:
        if scenario.story_key:
            return scenario.story_key
    return None


def _format_of(parsed: ParsedTestFile) -> PullFormat:
    return "robot" if parsed.format == "robot" else "feature"


def _collapse_separators(value: str) -> str:
    collapsed = re.sub(r"[_-]{2,}", "_", value)
    return collapsed.strip(" _-.")


def _sanitize(value: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", value, flags=re.UNICODE)
    return _collapse_separators(cleaned)
