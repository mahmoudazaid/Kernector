"""Static Robot Framework keyword extractor — no code execution."""

from __future__ import annotations

import re

from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import LineRange, ReusableComponent

_KEYWORD_HEADER = re.compile(r"^\*\*\*\s*Keywords\s*\*\*\*\s*$", re.IGNORECASE)
_SUITE_SECTION_HEADER = re.compile(
    r"^\*\*\*\s*(Test\s+Cases|Tasks)\s*\*\*\*\s*$", re.IGNORECASE
)
_SECTION = re.compile(r"^\*\*\*")
_DYNAMIC_NAME = re.compile(r"\$\{|@\{|&\{")


class RobotKeywordExtractor:
    """Extract ``keyword`` components from importable Robot resource files.

    ``.resource`` files and keyword-only ``.robot`` files are reusable. Suite
    ``.robot`` files with ``*** Test Cases ***`` or ``*** Tasks ***`` are
    skipped: Robot cannot import them as ``Resource``.
    """

    framework_id = "robot_framework"

    def extract(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> tuple[tuple[ReusableComponent, ...], tuple[str, ...]]:
        found: list[ReusableComponent] = []
        diagnostics: list[str] = []
        for file in files:
            if file.path.endswith(".resource"):
                items, diags = _extract_robot_keywords(file)
                found.extend(items)
                diagnostics.extend(diags)
                continue
            if not file.path.endswith(".robot"):
                continue
            if _has_suite_section(file.content):
                diagnostics.append(
                    "suite keywords not reusable "
                    f"(has Test Cases or Tasks): {file.path}"
                )
                continue
            items, diags = _extract_robot_keywords(file)
            found.extend(items)
            diagnostics.extend(diags)
        return tuple(found), tuple(diagnostics)


def _has_suite_section(content: str) -> bool:
    return any(_SUITE_SECTION_HEADER.match(line.strip()) for line in content.splitlines())

def _extract_robot_keywords(
    file: EvidenceFile,
) -> tuple[list[ReusableComponent], list[str]]:
    lines = file.content.splitlines()
    in_keywords = False
    found: list[ReusableComponent] = []
    diagnostics: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _KEYWORD_HEADER.match(line.strip()):
            in_keywords = True
            i += 1
            continue
        if in_keywords and _SECTION.match(line.strip()):
            break
        if not in_keywords:
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        if line.startswith(" ") or line.startswith("\t"):
            i += 1
            continue
        name = line.strip()
        start = i + 1
        i += 1
        while i < len(lines):
            body = lines[i]
            if not body.strip():
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and not (
                    lines[j].startswith(" ") or lines[j].startswith("\t")
                ):
                    break
                i += 1
                continue
            if _SECTION.match(body.strip()):
                break
            if not (body.startswith(" ") or body.startswith("\t")):
                break
            i += 1
        end = i
        if _DYNAMIC_NAME.search(name):
            diagnostics.append(
                f"unsupported robot keyword signature dropped: {file.path}:{start}"
            )
            continue
        doc = ""
        for body_line in lines[start:end]:
            stripped = body_line.strip()
            if stripped.startswith("[Documentation]"):
                doc = stripped.split("]", 1)[-1].strip()
                break
        found.append(
            ReusableComponent(
                component_id=f"keyword:{file.path}:{start}",
                kind="keyword",
                framework_id="robot_framework",
                signature=name,
                path=file.path,
                content_hash=file.content_hash,
                line_range=LineRange(start, end),
                documentation=doc,
            )
        )
    return found, diagnostics
