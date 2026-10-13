"""Robot Framework ``.robot`` parsing: ``Scenario:`` test cases and BDD steps."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.test_files.effective import effective_tags, file_story
from packs.software_delivery.test_files.models import (
    ParsedTestFile,
    TagRoles,
    TestFileScenario,
    TestFileTagConfig,
    TestStep,
)
from packs.software_delivery.test_files.tags import classify

_SECTION = re.compile(r"^\*+\s*([^*]+?)\s*\**$")
_SPACE_SEPARATOR = re.compile(r" {2,}|\t+")
_PIPE_SEPARATOR = re.compile(r" \|(?: |$)")
_SCENARIO = re.compile(r"^scenario:\s*", re.IGNORECASE)
_BDD_STEP = re.compile(r"^(given|when|then|and|but)\s+(\S.*)$", re.IGNORECASE)
_CONTINUATION = "..."
_TAGS_SETTING = "[tags]"
_TEST_CASES = "test cases"
_SETTINGS = "settings"
_DEFAULT_TAGS = "default tags"
_ALWAYS_TAGS = frozenset({"test tags", "force tags"})


@dataclass(slots=True)
class _SuiteTags:
    default: list[tuple[int, str]] = field(default_factory=list)
    always: list[tuple[int, str]] = field(default_factory=list)
    continues: list[tuple[int, str]] | None = None


@dataclass(slots=True)
class _Row:
    line: int
    indented: bool
    cells: list[str]


@dataclass(slots=True)
class _Step:
    line: int
    keyword: str
    arguments: list[str]


@dataclass(slots=True)
class _Case:
    line: int
    summary: str
    steps: list[_Step] = field(default_factory=list)
    tags: list[tuple[int, str]] = field(default_factory=list)
    has_tags: bool = False
    started: bool = False
    continues: _Step | list[tuple[int, str]] | None = None


def parse_robot(
    path: str, text: str, tags: TestFileTagConfig, max_scenarios: int | None = None
) -> ParsedTestFile:
    section = ""
    suite = _SuiteTags()
    cases: list[_Case] = []
    case: _Case | None = None
    for row in _rows(text):
        header = _SECTION.match(row.cells[0]) if not row.indented else None
        if header is not None:
            section = header.group(1).strip().lower()
            case = None
            continue
        if section == _SETTINGS:
            _settings_row(suite, row)
            continue
        if section != _TEST_CASES:
            continue
        if not row.indented:
            case = _start_case(path, row)
            if case is not None:
                if max_scenarios is not None and len(cases) >= max_scenarios:
                    raise TestFileValidationError(path, row.line, Reason.TOO_MANY_SCENARIOS)
                cases.append(case)
            continue
        if case is not None:
            _body_row(path, case, row)
    file_roles = classify([*suite.default, *suite.always], tags, "robot", path=path, scope="file")
    story = file_story(file_roles)
    default_plain = classify(suite.default, tags, "robot", path=path, scope="file").plain
    always_plain = classify(suite.always, tags, "robot", path=path, scope="file").plain
    return ParsedTestFile(
        path=path,
        format="robot",
        file_tags=file_roles,
        story_key=story,
        story_candidates=file_roles.candidate_keys,
        background=None,
        scenarios=tuple(
            _scenario(
                path,
                case,
                tags,
                file_roles=file_roles,
                story=story,
                inherited_plain=tuple(
                    dict.fromkeys(
                        (*(() if case.has_tags else default_plain), *always_plain)
                    )
                ),
            )
            for case in cases
        ),
    )


def _settings_row(suite: _SuiteTags, row: _Row) -> None:
    name = row.cells[0]
    values = [(row.line, cell) for cell in row.cells[1:]]
    if name == _CONTINUATION:
        if suite.continues is not None:
            suite.continues.extend(values)
        return
    folded = name.casefold()
    if folded == _DEFAULT_TAGS:
        suite.continues = suite.default
    elif folded in _ALWAYS_TAGS:
        suite.continues = suite.always
    else:
        suite.continues = None
        return
    suite.continues.extend(values)


def _rows(text: str) -> Iterator[_Row]:
    for number, raw in enumerate(text.splitlines(), start=1):
        if raw.startswith("|"):
            cells = _PIPE_SEPARATOR.split(raw[1:].rstrip().removesuffix("|").rstrip() + " ")
            cells = [cell.strip() for cell in cells]
            indented = not cells[0]
        else:
            indented = raw[:1].isspace()
            cells = _SPACE_SEPARATOR.split(raw.strip())
        while cells and not cells[0]:
            cells.pop(0)
        cells = _without_comment(cells)
        if cells:
            yield _Row(number, indented, cells)


def _without_comment(cells: list[str]) -> list[str]:
    for index, cell in enumerate(cells):
        if cell.startswith("#"):
            return cells[:index]
    return cells


def _start_case(path: str, row: _Row) -> _Case | None:
    name = row.cells[0]
    match = _SCENARIO.match(name)
    if match is None:
        return None
    summary = name[match.end() :].strip()
    if not summary:
        raise TestFileValidationError(path, row.line, Reason.EMPTY_SCENARIO_NAME)
    return _Case(line=row.line, summary=summary)


def _body_row(path: str, case: _Case, row: _Row) -> None:
    first = row.cells[0]
    if first == _CONTINUATION:
        if not case.started:
            raise TestFileValidationError(path, row.line, Reason.LEADING_CONTINUATION)
        if isinstance(case.continues, _Step):
            case.continues.arguments.extend(row.cells[1:])
        elif case.continues is not None:
            case.continues.extend((row.line, cell) for cell in row.cells[1:])
        return
    case.started = True
    if first.casefold() == _TAGS_SETTING:
        case.has_tags = True
        case.tags.extend((row.line, cell) for cell in row.cells[1:])
        case.continues = case.tags
        return
    step = _BDD_STEP.match(first)
    if step is None:
        case.continues = None
        return
    case.continues = _Step(row.line, step.group(1), [step.group(2), *row.cells[1:]])
    case.steps.append(case.continues)


def _scenario(
    path: str,
    case: _Case,
    config: TestFileTagConfig,
    *,
    file_roles: TagRoles,
    story: str | None,
    inherited_plain: tuple[str, ...],
) -> TestFileScenario:
    resolved = effective_tags(
        file_roles=file_roles,
        inherited_plain=inherited_plain,
        file_story=story,
        local=classify(case.tags, config, "robot", path=path, scope="scenario"),
        config=config,
    )
    return TestFileScenario(
        source_path=path,
        line=case.line,
        keyword="Scenario",
        summary=case.summary,
        kind=resolved.kind,
        outline=False,
        steps=tuple(
            TestStep(
                line=step.line,
                keyword=step.keyword,
                text=f"{step.keyword} {'    '.join(step.arguments)}",
                arguments=tuple(step.arguments),
            )
            for step in case.steps
        ),
        examples=(),
        tags=resolved.tags,
        story_key=resolved.story_key,
        xray_key=resolved.xray_key,
    )
