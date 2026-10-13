"""Gherkin ``.feature`` parsing for the supported subset documented in the pack README.

Unsupported or malformed constructs raise ``TestFileValidationError`` with the
file and line instead of being skipped. Doc-string content is captured before
any comment, tag, table or keyword recognition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.test_files.effective import effective_tags, file_story
from packs.software_delivery.test_files.models import (
    Background,
    DataTable,
    DocString,
    ExamplesBlock,
    ParsedTestFile,
    TableRow,
    TagRoles,
    TestFileScenario,
    TestFileTagConfig,
    TestStep,
)
from packs.software_delivery.test_files.tags import classify

_HEADER = re.compile(
    r"^(Feature|Background|Scenario Outline|Scenario Template|Scenario|Example"
    r"|Examples|Scenarios|Rule):(.*)$"
)
_STEP = re.compile(r"^(Given|When|Then|And|But|\*)\s+\S")
_LANGUAGE = re.compile(r"^#\s*language\s*:\s*(\S+)\s*$")
_TITLE_KEY = re.compile(r"\[([A-Z][A-Z0-9_]*-[1-9][0-9]*)\]")
_DOC_DELIMITERS = ('"""', "```")
_OUTLINE_KEYWORDS = frozenset({"Scenario Outline", "Scenario Template"})
_EXAMPLES_KEYWORDS = frozenset({"Examples", "Scenarios"})
_DIALECT = "en"


@dataclass(slots=True)
class _Step:
    line: int
    keyword: str
    text: str
    table: list[TableRow] = field(default_factory=list)
    doc: DocString | None = None


@dataclass(slots=True)
class _Examples:
    line: int
    keyword: str
    name: str
    tags: tuple[str, ...]
    header: TableRow | None = None
    rows: list[TableRow] = field(default_factory=list)


@dataclass(slots=True)
class _Block:
    line: int
    keyword: str
    name: str
    tags: list[tuple[int, str]]
    outline: bool = False
    steps: list[_Step] = field(default_factory=list)
    examples: list[_Examples] = field(default_factory=list)


@dataclass(slots=True)
class _OpenDoc:
    line: int
    delimiter: str
    media_type: str
    indent: int
    step: _Step
    lines: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _State:
    path: str
    max_scenarios: int | None = None
    feature_name: str | None = None
    feature_tags: list[tuple[int, str]] = field(default_factory=list)
    pending_tags: list[tuple[int, str]] = field(default_factory=list)
    background: _Block | None = None
    scenarios: list[_Block] = field(default_factory=list)
    block: _Block | None = None
    examples: _Examples | None = None
    attach: _Step | None = None
    doc: _OpenDoc | None = None

    def fail(self, line: int | None, reason: Reason) -> TestFileValidationError:
        return TestFileValidationError(self.path, line, reason)


def parse_gherkin(
    path: str, text: str, tags: TestFileTagConfig, max_scenarios: int | None = None
) -> ParsedTestFile:
    state = _State(path, max_scenarios)
    for number, raw in enumerate(text.splitlines(), start=1):
        _line(state, number, raw)
    if state.doc is not None:
        raise state.fail(state.doc.line, Reason.UNCLOSED_DOC_STRING)
    if state.pending_tags:
        raise state.fail(state.pending_tags[0][0], Reason.DANGLING_TAGS)
    if state.feature_name is None:
        raise state.fail(None, Reason.MISSING_FEATURE)
    _close_block(state)
    return _parsed(state, tags)


def _line(state: _State, number: int, raw: str) -> None:
    if state.doc is not None:
        _doc_line(state, raw)
        return
    stripped = raw.strip()
    if not stripped:
        return
    if stripped.startswith("#"):
        language = _LANGUAGE.match(stripped)
        if state.feature_name is None and language and language.group(1).lower() != _DIALECT:
            raise state.fail(number, Reason.UNSUPPORTED_LANGUAGE)
        return
    if stripped.startswith("@"):
        state.pending_tags.extend((number, tag) for tag in _tag_tokens(state, number, stripped))
        return
    header = _HEADER.match(stripped)
    if header is not None:
        _header(state, number, header.group(1), header.group(2).strip())
        return
    if state.feature_name is None:
        raise state.fail(number, Reason.MISSING_FEATURE)
    if state.pending_tags:
        raise state.fail(state.pending_tags[0][0], Reason.DANGLING_TAGS)
    if stripped.startswith("|"):
        _table_row(state, number, stripped)
    elif stripped.startswith(_DOC_DELIMITERS):
        _open_doc(state, number, stripped, len(raw) - len(raw.lstrip()))
    elif (step := _STEP.match(stripped)) is not None:
        _step(state, number, step.group(1), stripped)
    else:
        _description(state, number)


def _doc_line(state: _State, raw: str) -> None:
    doc = state.doc
    assert doc is not None
    if raw.strip() != doc.delimiter:
        doc.lines.append(raw)
        return
    doc.step.doc = DocString(
        line=doc.line,
        delimiter=doc.delimiter,
        media_type=doc.media_type,
        lines=tuple(doc.lines),
        indent=doc.indent,
    )
    state.doc = None
    state.attach = None


def _tag_tokens(state: _State, number: int, stripped: str) -> list[str]:
    tokens: list[str] = []
    for token in stripped.split():
        if token.startswith("#"):
            break
        if not token.startswith("@") or len(token) == 1:
            raise state.fail(number, Reason.MALFORMED_TAG)
        tokens.append(token[1:])
    return tokens


def _header(state: _State, number: int, keyword: str, name: str) -> None:
    if keyword == "Rule":
        raise state.fail(number, Reason.UNSUPPORTED_RULE)
    tags, state.pending_tags = state.pending_tags, []
    state.attach = None
    if keyword == "Feature":
        if state.feature_name is not None:
            raise state.fail(number, Reason.DUPLICATE_FEATURE)
        state.feature_name = name
        state.feature_tags = tags
        return
    if state.feature_name is None:
        raise state.fail(number, Reason.MISSING_FEATURE)
    if keyword in _EXAMPLES_KEYWORDS:
        _start_examples(state, number, keyword, name, tags)
        return
    _close_block(state)
    if keyword == "Background":
        _start_background(state, number, name, tags)
        return
    if not name:
        raise state.fail(number, Reason.EMPTY_SCENARIO_NAME)
    if state.max_scenarios is not None and len(state.scenarios) >= state.max_scenarios:
        raise state.fail(number, Reason.TOO_MANY_SCENARIOS)
    state.block = _Block(number, keyword, name, tags, outline=keyword in _OUTLINE_KEYWORDS)
    state.scenarios.append(state.block)


def _start_background(
    state: _State, number: int, name: str, tags: list[tuple[int, str]]
) -> None:
    if tags:
        raise state.fail(tags[0][0], Reason.DANGLING_TAGS)
    if state.scenarios:
        raise state.fail(number, Reason.BACKGROUND_AFTER_SCENARIO)
    if state.background is not None:
        raise state.fail(number, Reason.DUPLICATE_BACKGROUND)
    state.background = state.block = _Block(number, "Background", name, [])


def _start_examples(
    state: _State, number: int, keyword: str, name: str, tags: list[tuple[int, str]]
) -> None:
    block = state.block
    if block is None or not block.outline:
        raise state.fail(number, Reason.EXAMPLES_OUTSIDE_OUTLINE)
    _close_examples(state)
    state.examples = _Examples(number, keyword, name, tuple(tag for _line, tag in tags))
    block.examples.append(state.examples)


def _close_examples(state: _State) -> None:
    examples = state.examples
    if examples is not None and (examples.header is None or not examples.rows):
        raise state.fail(examples.line, Reason.EXAMPLES_WITHOUT_ROWS)
    state.examples = None


def _close_block(state: _State) -> None:
    _close_examples(state)
    block = state.block
    if block is not None and block.outline and not block.examples:
        raise state.fail(block.line, Reason.OUTLINE_WITHOUT_EXAMPLES)
    state.block = None


def _table_row(state: _State, number: int, stripped: str) -> None:
    cells = _row_cells(stripped)
    if cells is None:
        raise state.fail(number, Reason.MALFORMED_TABLE_ROW)
    row = TableRow(number, cells)
    step = state.attach
    if step is not None and step.doc is None:
        _append_row(state, step.table, row)
        return
    examples = state.examples
    if examples is None:
        raise state.fail(number, Reason.ORPHAN_TABLE)
    if examples.header is None:
        examples.header = row
        return
    if len(cells) != len(examples.header.cells):
        raise state.fail(number, Reason.INCONSISTENT_ROW_WIDTH)
    examples.rows.append(row)


def _append_row(state: _State, rows: list[TableRow], row: TableRow) -> None:
    if rows and len(row.cells) != len(rows[0].cells):
        raise state.fail(row.line, Reason.INCONSISTENT_ROW_WIDTH)
    rows.append(row)


def _row_cells(stripped: str) -> tuple[str, ...] | None:
    """Split on unescaped ``|``; escapes such as ``\\|`` are kept as written."""
    if len(stripped) < 2 or not stripped.endswith("|"):
        return None
    cells: list[str] = []
    current: list[str] = []
    index = 1
    while index < len(stripped):
        char = stripped[index]
        if char == "\\" and index + 1 < len(stripped):
            current.append(stripped[index : index + 2])
            index += 2
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    if "".join(current).strip() or not cells:
        return None
    return tuple(cells)


def _open_doc(state: _State, number: int, stripped: str, indent: int) -> None:
    step = state.attach
    if step is None or step.table or step.doc is not None:
        raise state.fail(number, Reason.ORPHAN_DOC_STRING)
    delimiter = '"""' if stripped.startswith('"""') else "```"
    state.doc = _OpenDoc(number, delimiter, stripped[len(delimiter) :].strip(), indent, step)


def _step(state: _State, number: int, keyword: str, stripped: str) -> None:
    block = state.block
    if block is None:
        raise state.fail(number, Reason.STEP_OUTSIDE_SCENARIO)
    if state.examples is not None:
        raise state.fail(number, Reason.UNEXPECTED_LINE)
    step = _Step(number, keyword, stripped)
    block.steps.append(step)
    state.attach = step


def _description(state: _State, number: int) -> None:
    state.attach = None
    examples = state.examples
    if examples is not None:
        if examples.header is not None:
            raise state.fail(number, Reason.UNEXPECTED_LINE)
        return
    block = state.block
    if block is not None and block.steps:
        raise state.fail(number, Reason.UNEXPECTED_LINE)
    if block is None and state.scenarios:
        raise state.fail(number, Reason.UNEXPECTED_LINE)


def _parsed(state: _State, config: TestFileTagConfig) -> ParsedTestFile:
    roles = classify(state.feature_tags, config, "gherkin", path=state.path, scope="file")
    story = file_story(roles)
    if story is None and not roles.candidate_keys:
        title = _TITLE_KEY.search(state.feature_name or "")
        story = None if title is None else title.group(1)
    background = state.background
    return ParsedTestFile(
        path=state.path,
        format="gherkin",
        file_tags=roles,
        story_key=story,
        story_candidates=roles.candidate_keys,
        background=(
            None
            if background is None
            else Background(background.line, background.name, _steps(background))
        ),
        scenarios=tuple(
            _scenario(state.path, block, config, roles, story) for block in state.scenarios
        ),
    )


def _steps(block: _Block) -> tuple[TestStep, ...]:
    return tuple(
        TestStep(
            line=step.line,
            keyword=step.keyword,
            text=step.text,
            data_table=(
                DataTable(step.table[0].line, tuple(step.table)) if step.table else None
            ),
            doc_string=step.doc,
        )
        for step in block.steps
    )


def _scenario(
    path: str,
    block: _Block,
    config: TestFileTagConfig,
    roles: TagRoles,
    story: str | None,
) -> TestFileScenario:
    resolved = effective_tags(
        file_roles=roles,
        inherited_plain=roles.plain,
        file_story=story,
        local=classify(block.tags, config, "gherkin", path=path, scope="scenario"),
        config=config,
    )
    return TestFileScenario(
        source_path=path,
        line=block.line,
        keyword=block.keyword,
        summary=block.name,
        kind=resolved.kind,
        outline=block.outline,
        steps=_steps(block),
        examples=tuple(
            ExamplesBlock(
                line=examples.line,
                keyword=examples.keyword,
                name=examples.name,
                tags=examples.tags,
                header=examples.header,  # type: ignore[arg-type]
                rows=tuple(examples.rows),
            )
            for examples in block.examples
        ),
        tags=resolved.tags,
        story_key=resolved.story_key,
        xray_key=resolved.xray_key,
    )
