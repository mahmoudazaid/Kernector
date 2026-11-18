"""Playwright / Node test-file path extractor — path conventions only."""

from __future__ import annotations

from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import LineRange, ReusableComponent

_SCRIPT_SUFFIXES = (".ts", ".js", ".mjs", ".cjs")


class PlaywrightSpecExtractor:
    """Extract Playwright specs as ``page_object`` components by path."""

    framework_id = "playwright"

    def extract(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> tuple[tuple[ReusableComponent, ...], tuple[str, ...]]:
        found: list[ReusableComponent] = []
        for file in files:
            if not _is_playwright_spec(file.path):
                continue
            lines = file.content.splitlines()
            end = len(lines) if lines else 1
            found.append(
                ReusableComponent(
                    component_id=f"page_object:{file.path}",
                    kind="page_object",
                    framework_id="playwright",
                    signature=file.path.rsplit("/", 1)[-1],
                    path=file.path,
                    content_hash=file.content_hash,
                    line_range=LineRange(1, end),
                    documentation="",
                )
            )
        return tuple(found), ()


def _is_playwright_spec(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if not name.endswith(_SCRIPT_SUFFIXES):
        return False
    stem = name.rsplit(".", 1)[0]
    if stem.endswith(".spec") or stem.endswith(".test"):
        return True
    return path.startswith("e2e/") and name.endswith((".ts", ".js"))
