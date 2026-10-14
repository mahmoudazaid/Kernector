"""Write Xray test keys back into ``.robot`` / ``.feature`` text (#399).

Pure over the caller's text: scenario locations come from the parser layout
and marker forms from the shared tag classifier. Only Xray markers and bare
copies of the assigned key are removed; every other tag, comment and line is
kept. Nothing is read from or written to disk.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.test_files.layout import ScenarioLayout, TagRow
from packs.software_delivery.test_files.models import (
    ParsedTestFile,
    TestFileScenario,
    TestFileTagConfig,
)
from packs.software_delivery.test_files.parser import parse_test_file_layout
from packs.software_delivery.test_files.tags import TagSyntax, tag_role

WriteStatus = Literal["TAGGED", "REPLACED", "NORMALIZED", "UNCHANGED"]
WRITE_STATUSES: tuple[WriteStatus, ...] = ("TAGGED", "REPLACED", "NORMALIZED", "UNCHANGED")

_BOM = "\ufeff"
_ROBOT_SEPARATOR = "    "
_TAGS_SETTING = "[Tags]"
_NO_NEWLINE = "\\ No newline at end of file\n"
_Edits = dict[int, list[str]]


@dataclass(frozen=True, slots=True)
class ScenarioRewrite:
    """Outcome for one mapped scenario; ``previous_key`` is its parsed Xray key."""

    line: int
    summary: str
    key: str
    previous_key: str | None
    status: WriteStatus


@dataclass(frozen=True, slots=True)
class FileRewrite:
    path: str
    content: str
    changed: bool
    diff: str
    scenarios: tuple[ScenarioRewrite, ...]


def rewrite_file(
    path: str, text: str, keys: Mapping[str, str], tags: TestFileTagConfig
) -> FileRewrite:
    """Tag the scenarios named in ``keys`` (summary to Xray key) with their keys.

    Raises:
        TestFileValidationError: The file does not parse, a summary is not in
            the file, a line that must change cannot be rewritten safely, or
            the rewrite would change another tag role of a scenario.
    """
    parsed, layout = parse_test_file_layout(path, text, tags)
    missing = set(keys) - {scenario.summary for scenario in parsed.scenarios}
    if missing:
        raise TestFileValidationError(path, None, Reason.UNKNOWN_SCENARIO)
    body = text.removeprefix(_BOM)
    lines = body.splitlines(keepends=True)
    eol = next((ending for line in lines if (ending := _ending(line))), "\n")
    edits: _Edits = {}
    results: list[ScenarioRewrite] = []
    for scenario, where in zip(parsed.scenarios, layout.scenarios, strict=True):
        key = keys.get(scenario.summary)
        if key is None:
            continue
        if parsed.format == "gherkin":
            changes = _gherkin_edits(path, lines, where, key, tags, eol)
        else:
            changes = _robot_edits(path, lines, where, key, tags, eol, layout.default_tags)
        edits.update(changes)
        results.append(
            ScenarioRewrite(
                line=scenario.line,
                summary=scenario.summary,
                key=key,
                previous_key=scenario.xray_key,
                status=_status(scenario.xray_key, key, changed=bool(changes)),
            )
        )
    new_lines = [out for index, line in enumerate(lines) for out in edits.get(index, [line])]
    new_body = "".join(new_lines)
    if new_body != body:
        _guard_roles(path, parsed, new_body, keys, tags)
    return FileRewrite(
        path=path,
        content=text[: len(text) - len(body)] + new_body,
        changed=new_body != body,
        diff="" if new_body == body else _diff(path, lines, new_lines),
        scenarios=tuple(results),
    )


def _status(previous: str | None, key: str, *, changed: bool) -> WriteStatus:
    if not changed:
        return "UNCHANGED"
    if previous is None:
        return "TAGGED"
    return "REPLACED" if previous != key else "NORMALIZED"


@dataclass(slots=True)
class _Anchor:
    """Where the canonical marker goes: first old marker, else first bare copy."""

    marker: tuple[int, int] | None = None
    bare: tuple[int, int] | None = None

    @property
    def position(self) -> tuple[int, int] | None:
        return self.marker or self.bare


def _strip_identity(
    row: TagRow, key: str, tags: TestFileTagConfig, syntax: TagSyntax, anchor: _Anchor
) -> list[str]:
    """Row cells without Xray markers and bare copies of ``key``; records the anchor."""
    kept: list[str] = []
    for cell in row.cells:
        role, value = tag_role(cell, tags, syntax)
        if role == "xray":
            anchor.marker = anchor.marker or (row.line, len(kept))
        elif role == "candidate" and value == key:
            anchor.bare = anchor.bare or (row.line, len(kept))
        else:
            kept.append(cell)
    return kept


def _gherkin_edits(
    path: str,
    lines: list[str],
    where: ScenarioLayout,
    key: str,
    tags: TestFileTagConfig,
    eol: str,
) -> _Edits:
    """Comment lines and tag lines carrying a ``#`` token are never edited."""
    canonical = f"{tags.test_marker}:{key}"
    anchor = _Anchor()
    editable = [row for row in where.tag_rows if row.comment is None]
    for row in where.tag_rows:
        if row.comment is not None and any(
            tag_role(cell, tags, "gherkin")[0] == "xray" for cell in row.cells
        ):
            raise TestFileValidationError(path, row.line, Reason.COMMENTED_TAG_LINE)
    cells = {row.line: _strip_identity(row, key, tags, "gherkin", anchor) for row in editable}
    edits: _Edits = {}
    position = anchor.position
    if position is not None:
        cells[position[0]].insert(position[1], canonical)
    elif where.tag_rows and where.tag_rows[-1].comment is None:
        cells[where.tag_rows[-1].line].append(canonical)
    else:
        index = where.line - 1
        ending = _ending(lines[index]) or eol
        edits[index] = [f"{where.header_indent}@{canonical}{ending}", lines[index]]
    for row in editable:
        new = cells[row.line]
        if new == list(row.cells):
            continue
        index = row.line - 1
        tokens = " ".join(f"@{cell}" for cell in new)
        edits[index] = [f"{row.indent}{tokens}{_ending(lines[index])}"] if new else []
    return edits


def _robot_edits(
    path: str,
    lines: list[str],
    where: ScenarioLayout,
    key: str,
    tags: TestFileTagConfig,
    eol: str,
    default_tags: tuple[str, ...],
) -> _Edits:
    """Merge the ``[Tags]`` rows into the first; a new row copies ``Default Tags``.

    Robot drops ``Default Tags`` for a test with its own ``[Tags]``, so they
    are copied verbatim into an inserted row. A removed row's comment stays on
    its line as a standalone comment row.
    """
    pipe = [where.line] if where.header_pipe else [r.line for r in where.tag_rows if r.pipe]
    if pipe:
        raise TestFileValidationError(path, pipe[0], Reason.PIPE_ROWS_UNSUPPORTED)
    rows = where.tag_rows
    source = tuple(cell for row in rows for cell in row.cells) if rows else default_tags
    anchor = _Anchor()
    cells = _strip_identity(TagRow(0, "", source, None, ""), key, tags, "robot", anchor)
    position = anchor.position
    cells.insert(len(cells) if position is None else position[1], f"{tags.test_marker} {key}")
    if not rows:
        index = where.line - 1
        header = lines[index]
        indent = _ROBOT_SEPARATOR if where.body_indent is None else where.body_indent
        row = indent + _ROBOT_SEPARATOR.join([_TAGS_SETTING, *cells])
        ending = _ending(header)
        return {index: [header, row + ending] if ending else [header + eol, row]}
    first = rows[0]
    if len(rows) == 1 and cells == list(first.cells):
        return {}
    index = first.line - 1
    comment = [] if first.comment is None else [first.comment]
    merged = first.indent + _ROBOT_SEPARATOR.join([first.name, *cells, *comment])
    edits: _Edits = {index: [merged + _ending(lines[index])]}
    for row in rows[1:]:
        index = row.line - 1
        ending = _ending(lines[index])
        edits[index] = [] if row.comment is None else [row.indent + row.comment + ending]
    return edits


def _guard_roles(
    path: str,
    before: ParsedTestFile,
    new_body: str,
    keys: Mapping[str, str],
    tags: TestFileTagConfig,
) -> None:
    """Re-parse the result: mapped scenarios carry their key and keep other roles."""
    after, _layout = parse_test_file_layout(path, new_body, tags)
    for old, new in zip(before.scenarios, after.scenarios, strict=True):
        key = keys.get(old.summary)
        if key is None:
            continue
        if new.xray_key != key or _roles(before, old, key) != _roles(after, new, key):
            raise TestFileValidationError(path, old.line, Reason.ROLE_CHANGE)


def _roles(parsed: ParsedTestFile, scenario: TestFileScenario, key: str) -> tuple[object, ...]:
    """Non-Xray roles; the Robot story choice mirrors ``matching.resolve_story``."""
    local = scenario.tags.local
    choice = None
    if parsed.format == "robot":
        bare = next((k for k in local.candidate_keys if k != key), None)
        choice = local.story_key or bare or scenario.story_key
    return (
        scenario.story_key,
        scenario.kind,
        frozenset(scenario.tags.effective_plain),
        replace(scenario.tags.inherited, plain=()),
        choice,
    )


def _ending(line: str) -> str:
    body = line.splitlines()[0] if line else ""
    return line[len(body) :]


def _diff(path: str, old: list[str], new: list[str]) -> str:
    out: list[str] = []
    for line in difflib.unified_diff(old, new, f"a/{path}", f"b/{path}"):
        out.append(line)
        if not _ending(line):
            out.append("\n" + _NO_NEWLINE)
    return "".join(out)
