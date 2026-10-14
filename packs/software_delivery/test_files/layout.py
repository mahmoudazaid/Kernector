"""Source locations the parsers report for write-back (#399).

Kept apart from ``ParsedTestFile`` so the preview payload and its strict MCP
schema never change.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TagRow:
    """One source line holding scenario tags.

    Robot: a ``[Tags]`` row (``name`` as written) or its ``...`` continuation;
    ``cells`` excludes the name. Gherkin: an ``@`` line with ``name`` empty and
    ``cells`` the tags without ``@``. ``comment`` is the raw text from the
    ``#`` cell or token to the end of the line.
    """

    line: int
    name: str
    cells: tuple[str, ...]
    comment: str | None
    indent: str
    pipe: bool = False


@dataclass(frozen=True, slots=True)
class ScenarioLayout:
    """Where one parsed scenario sits; same order as ``ParsedTestFile.scenarios``.

    ``end_line`` and ``body_indent`` are Robot-only (``None`` for Gherkin).
    """

    line: int
    tag_rows: tuple[TagRow, ...]
    header_indent: str = ""
    header_pipe: bool = False
    end_line: int | None = None
    body_indent: str | None = None


@dataclass(frozen=True, slots=True)
class FileLayout:
    scenarios: tuple[ScenarioLayout, ...]
    default_tags: tuple[str, ...] = ()
