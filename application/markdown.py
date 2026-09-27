"""Deterministic CommonMark rendering for neutral typed documents.

Pure shared application helper — not an agent-callable Tool. Callers map domain
content into ``MarkdownDocument`` / ``MarkdownSection`` and pass the result of
``render_markdown`` elsewhere (for example Drive export via composition).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from application.errors import ApplicationValidationError

__all__ = (
    "MarkdownDocument",
    "MarkdownSection",
    "render_markdown",
)


def _require_text(value: object, field_name: str) -> str:
    """Reject anything that is not a non-blank string."""
    if not isinstance(value, str):
        raise ApplicationValidationError(
            f"{field_name} must be a non-empty string, got {type(value).__name__}"
        )
    if not value.strip():
        raise ApplicationValidationError(f"{field_name} must be non-empty")
    return value


def _require_string(value: object, field_name: str) -> str:
    """Reject non-strings; blank strings remain allowed."""
    if not isinstance(value, str):
        raise ApplicationValidationError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    return value


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    """Reject non-sequence collections (and strings/bytes)."""
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ApplicationValidationError(
            f"{field_name} must be a sequence, got {type(value).__name__}"
        )
    return value


_MIN_SECTION_LEVEL = 2
_MAX_SECTION_LEVEL = 6
_MAX_CODE_LANGUAGE_CHARS = 32
_CODE_LANGUAGE_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_+-"
)


@dataclass(frozen=True, slots=True)
class MarkdownSection:
    """One section: heading plus optional paragraphs, lists, and a code block.

    ``level`` is the heading depth (2 → ``##`` … 6 → ``######``). ``code_block``
    is emitted verbatim inside a fence; everything else is escaped field text.
    """

    heading: str
    paragraphs: tuple[str, ...] = ()
    bullet_items: tuple[str, ...] = ()
    ordered_items: tuple[str, ...] = ()
    code_block: str = ""
    code_language: str = ""
    level: int = _MIN_SECTION_LEVEL

    def __post_init__(self) -> None:
        _require_text(self.heading, "heading")
        paragraphs = _require_sequence(self.paragraphs, "paragraphs")
        bullet_items = _require_sequence(self.bullet_items, "bullet_items")
        ordered_items = _require_sequence(self.ordered_items, "ordered_items")
        object.__setattr__(self, "paragraphs", tuple(paragraphs))
        object.__setattr__(self, "bullet_items", tuple(bullet_items))
        object.__setattr__(self, "ordered_items", tuple(ordered_items))
        for index, paragraph in enumerate(self.paragraphs):
            _require_string(paragraph, f"paragraphs[{index}]")
        for index, item in enumerate(self.bullet_items):
            _require_text(item, f"bullet_items[{index}]")
        for index, item in enumerate(self.ordered_items):
            _require_text(item, f"ordered_items[{index}]")
        _require_string(self.code_block, "code_block")
        language = _require_string(self.code_language, "code_language")
        if len(language) > _MAX_CODE_LANGUAGE_CHARS or not set(language) <= (
            _CODE_LANGUAGE_CHARS
        ):
            raise ApplicationValidationError("code_language is invalid")
        if (
            not isinstance(self.level, int)
            or isinstance(self.level, bool)
            or not _MIN_SECTION_LEVEL <= self.level <= _MAX_SECTION_LEVEL
        ):
            raise ApplicationValidationError(
                f"level must be an int from {_MIN_SECTION_LEVEL} to "
                f"{_MAX_SECTION_LEVEL}"
            )


@dataclass(frozen=True, slots=True)
class MarkdownDocument:
    """A Markdown document with a required title and zero or more sections."""

    title: str
    sections: tuple[MarkdownSection, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.title, "title")
        sections = _require_sequence(self.sections, "sections")
        object.__setattr__(self, "sections", tuple(sections))
        for index, section in enumerate(self.sections):
            if not isinstance(section, MarkdownSection):
                raise ApplicationValidationError(
                    f"sections[{index}] must be a MarkdownSection, "
                    f"got {type(section).__name__}"
                )


_LINE_BREAKS = str.maketrans(
    {
        "\r": " ",
        "\n": " ",
        "\u2028": " ",  # line separator
        "\u2029": " ",  # paragraph separator
    }
)

# Inline specials plus block leaders / HTML so field text cannot inject structure.
_MARKDOWN_SPECIALS = frozenset("\\`*_[]#-+>|.<)~")


def _normalize_text(value: str) -> str:
    """Collapse line breaks and whitespace; strip ends."""
    collapsed = " ".join(value.translate(_LINE_BREAKS).split())
    return collapsed


def _escape_markdown(value: str) -> str:
    """Backslash-escape structural Markdown specials in field text."""
    return "".join(f"\\{char}" if char in _MARKDOWN_SPECIALS else char for char in value)


def _field_text(value: str) -> str:
    """Normalize then escape untrusted field text for safe inline emission."""
    return _escape_markdown(_normalize_text(value))


def render_markdown(document: MarkdownDocument) -> str:
    """Render ``document`` to deterministic CommonMark-compatible Markdown.

    Args:
        document: Validated typed document.

    Returns:
        Markdown text with exactly one trailing newline and no trailing spaces.
    """
    blocks: list[str] = [f"# {_field_text(document.title)}"]
    for section in document.sections:
        blocks.append(f"{'#' * section.level} {_field_text(section.heading)}")
        for paragraph in section.paragraphs:
            normalized = _normalize_text(paragraph)
            if not normalized:
                continue
            blocks.append(_escape_markdown(normalized))
        if section.bullet_items:
            bullets = "\n".join(
                f"- {_field_text(item)}" for item in section.bullet_items
            )
            blocks.append(bullets)
        if section.ordered_items:
            ordered = "\n".join(
                f"{index}. {_field_text(item)}"
                for index, item in enumerate(section.ordered_items, start=1)
            )
            blocks.append(ordered)
        code = _code_block(section.code_block, section.code_language)
        if code:
            blocks.append(code)
    return "\n\n".join(blocks) + "\n"


def _code_block(value: str, language: str) -> str:
    """Fence verbatim text; the fence outgrows any backtick run inside."""
    lines = [
        line.rstrip()
        for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        return ""
    body = "\n".join(lines)
    fence = "`" * max(3, _longest_backtick_run(body) + 1)
    return f"{fence}{language}\n{body}\n{fence}"


def _longest_backtick_run(value: str) -> int:
    longest = current = 0
    for char in value:
        current = current + 1 if char == "`" else 0
        longest = max(longest, current)
    return longest
