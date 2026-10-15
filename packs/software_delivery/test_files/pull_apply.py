"""Apply pull proposals to caller-supplied file text (#400).

Inserts Robot scenarios inside ``*** Test Cases ***`` (before later sections),
appends Gherkin scenarios after the last scenario, and back-fills XRay tags via
``rewrite_file`` only when summary uniqueness holds. Never writes disk.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.test_files.from_xray import ScenarioRender
from packs.software_delivery.test_files.models import ParsedTestFile, TestFileTagConfig
from packs.software_delivery.test_files.parser import parse_test_file, parse_test_file_layout
from packs.software_delivery.test_files.writeback import rewrite_file

_SECTION = re.compile(r"^\*+\s*([^*]+?)\s*\**\s*$")
_BOM = "\ufeff"
_NO_NEWLINE = "\\ No newline at end of file\n"
_AFTER_TEST_CASES = frozenset({"keywords", "variables", "comments", "tasks"})


@dataclass(frozen=True, slots=True)
class FileProposal:
    path: str
    content: str
    diff: str
    changed: bool


@dataclass(frozen=True, slots=True)
class AddEdit:
    path: str
    render: ScenarioRender


@dataclass(frozen=True, slots=True)
class BackfillEdit:
    path: str
    summary: str
    key: str


def apply_pull_edits(
    inventory: Mapping[str, str],
    *,
    adds: Sequence[AddEdit],
    backfills: Sequence[BackfillEdit],
    new_files: Mapping[str, str],
    tags: TestFileTagConfig,
    parsed_by_path: Mapping[str, ParsedTestFile],
) -> tuple[FileProposal, ...]:
    """Aggregate adds/backfills/new files into one content+diff per changed path.

    Raises:
        TestFileValidationError: Uniqueness for backfill fails, or verify fails.
    """
    working = dict(inventory)
    for path, content in new_files.items():
        if path in working:
            raise TestFileValidationError(path, None, Reason.DUPLICATE_FILE_PATH)
        working[path] = content

    backfill_by_path: dict[str, dict[str, str]] = {}
    for edit in backfills:
        _require_unique_summary(parsed_by_path[edit.path], edit.summary)
        backfill_by_path.setdefault(edit.path, {})[edit.summary] = edit.key

    for path, keys in backfill_by_path.items():
        rewrite = rewrite_file(path, working[path], keys, tags)
        working[path] = rewrite.content

    adds_by_path: dict[str, list[ScenarioRender]] = {}
    for edit in adds:
        adds_by_path.setdefault(edit.path, []).append(edit.render)

    for path, renders in adds_by_path.items():
        before = working[path]
        after = before
        for render in renders:
            after = insert_scenario(path, after, render, tags)
        working[path] = after

    proposals: list[FileProposal] = []
    for path, content in working.items():
        original = inventory.get(path, "")
        if content == original and path not in new_files:
            continue
        if path in inventory:
            _verify(path, inventory[path], content, tags, adds_by_path.get(path, ()), backfill_by_path.get(path, {}))
        bom = content[: len(content) - len(content.removeprefix(_BOM))] if content.startswith(_BOM) else ""
        body = content.removeprefix(_BOM)
        old_body = original.removeprefix(_BOM)
        old_lines = old_body.splitlines(keepends=True)
        new_lines = body.splitlines(keepends=True)
        proposals.append(
            FileProposal(
                path=path,
                content=content,
                diff=_diff(path, bom, old_lines, new_lines) if path in inventory else _diff(path, "", [], new_lines),
                changed=True,
            )
        )
    return tuple(proposals)


def insert_scenario(
    path: str, text: str, render: ScenarioRender, tags: TestFileTagConfig
) -> str:
    """Insert ``render.text`` into an existing file without touching other bodies."""
    bom = text[: len(text) - len(text.removeprefix(_BOM))] if text.startswith(_BOM) else ""
    body = text.removeprefix(_BOM)
    lines = body.splitlines(keepends=True)
    eol = next((ending for line in lines if (ending := _ending(line))), "\n")
    block = render.text.rstrip("\n") + eol
    if render.format == "robot":
        index = _robot_insert_index(path, lines)
        insertion = [block]
        if index > 0 and lines and not lines[index - 1].endswith(("\n", "\r\n")):
            insertion.insert(0, eol)
        elif index > 0 and lines and lines[index - 1].endswith(("\n", "\r\n")):
            insertion.insert(0, eol)
        if index < len(lines):
            insertion.append(eol)
        lines[index:index] = insertion
    else:
        if lines and not lines[-1].endswith(("\n", "\r\n")):
            lines[-1] = lines[-1] + eol
        if lines and lines[-1].strip():
            lines.append(eol)
        lines.append(block if block.endswith(("\n", "\r\n")) else block + eol)
    return bom + "".join(lines)


def _robot_insert_index(path: str, lines: list[str]) -> int:
    """Index of the first section after Test Cases, or len(lines)."""
    in_cases = False
    for index, line in enumerate(lines):
        match = _SECTION.match(line.splitlines()[0] if line else "")
        if match is None:
            continue
        name = match.group(1).strip().lower()
        if name == "test cases":
            in_cases = True
            continue
        if in_cases and name in _AFTER_TEST_CASES:
            return index
    if not in_cases:
        raise TestFileValidationError(path, None, Reason.UNEXPECTED_LINE)
    return len(lines)


def _require_unique_summary(parsed: ParsedTestFile, summary: str) -> None:
    matches = [s for s in parsed.scenarios if s.summary == summary]
    if len(matches) != 1:
        raise TestFileValidationError(parsed.path, None, Reason.DUPLICATE_SCENARIO_NAME)


def _verify(
    path: str,
    before_text: str,
    after_text: str,
    tags: TestFileTagConfig,
    adds: Sequence[ScenarioRender],
    backfills: Mapping[str, str],
) -> None:
    before, _ = parse_test_file_layout(path, before_text, tags)
    after = parse_test_file(path, after_text, tags)
    before_by_summary = {s.summary: s for s in before.scenarios}
    for summary, scenario in before_by_summary.items():
        found = next((s for s in after.scenarios if s.summary == summary), None)
        if found is None:
            raise TestFileValidationError(path, scenario.line, Reason.ROLE_CHANGE)
        if summary in backfills:
            if found.xray_key != backfills[summary]:
                raise TestFileValidationError(path, scenario.line, Reason.ROLE_CHANGE)
        else:
            old_steps = tuple(step.text for step in scenario.steps)
            new_steps = tuple(step.text for step in found.steps)
            if old_steps != new_steps:
                raise TestFileValidationError(path, scenario.line, Reason.ROLE_CHANGE)
    for render in adds:
        found = next((s for s in after.scenarios if s.summary == render.summary), None)
        if found is None or found.xray_key != render.key:
            raise TestFileValidationError(path, None, Reason.UNKNOWN_SCENARIO)


def _ending(line: str) -> str:
    body = line.splitlines()[0] if line else ""
    return line[len(body) :]


def _diff(path: str, bom: str, old: list[str], new: list[str]) -> str:
    if old:
        old = [bom + old[0], *old[1:]]
    if new:
        new = [bom + new[0], *new[1:]] if bom else new
    out: list[str] = []
    for line in difflib.unified_diff(old, new, f"a/{path}", f"b/{path}"):
        out.append(line)
        if not _ending(line):
            out.append("\n" + _NO_NEWLINE)
    return "".join(out)
