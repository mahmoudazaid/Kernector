"""Typed scenario specs extracted from ``.robot`` and ``.feature`` files (#396)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TestFileFormat = Literal["robot", "gherkin"]
ScenarioKind = Literal["manual", "cucumber"]


@dataclass(frozen=True, slots=True)
class TestFileTagConfig:
    """Configured tag names; composition supplies them from ``XRAY_*`` settings."""

    __test__ = False

    test_marker: str
    story_marker: str
    manual_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TagRoles:
    """Tags of one scope, split into roles; ``plain`` keeps source order."""

    xray_key: str | None = None
    story_key: str | None = None
    candidate_keys: tuple[str, ...] = ()
    plain: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioTags:
    """File-scope (inherited) and scenario-scope (local) roles, kept apart."""

    inherited: TagRoles = field(default_factory=TagRoles)
    local: TagRoles = field(default_factory=TagRoles)
    effective_plain: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TableRow:
    line: int
    cells: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DataTable:
    line: int
    rows: tuple[TableRow, ...]


@dataclass(frozen=True, slots=True)
class DocString:
    """Doc string with its delimiter, media type and verbatim source lines.

    ``indent`` is the opening delimiter's column; content indentation is
    relative to it.
    """

    line: int
    delimiter: str
    media_type: str
    lines: tuple[str, ...]
    indent: int


@dataclass(frozen=True, slots=True)
class TestStep:
    """One step. Robot fills ``arguments``; ``text`` is the step as written."""

    __test__ = False

    line: int
    keyword: str
    text: str
    arguments: tuple[str, ...] = ()
    data_table: DataTable | None = None
    doc_string: DocString | None = None


@dataclass(frozen=True, slots=True)
class ExamplesBlock:
    line: int
    keyword: str
    name: str
    tags: tuple[str, ...]
    header: TableRow
    rows: tuple[TableRow, ...]


@dataclass(frozen=True, slots=True)
class Background:
    line: int
    name: str
    steps: tuple[TestStep, ...]


@dataclass(frozen=True, slots=True)
class TestFileScenario:
    """One scenario; ``story_key`` and ``xray_key`` are the effective values."""

    __test__ = False

    source_path: str
    line: int
    keyword: str
    summary: str
    kind: ScenarioKind
    outline: bool
    steps: tuple[TestStep, ...]
    examples: tuple[ExamplesBlock, ...]
    tags: ScenarioTags
    story_key: str | None
    xray_key: str | None


@dataclass(frozen=True, slots=True)
class ParsedTestFile:
    path: str
    format: TestFileFormat
    file_tags: TagRoles
    story_key: str | None
    story_candidates: tuple[str, ...]
    background: Background | None
    scenarios: tuple[TestFileScenario, ...]
