"""Deterministic CommonMark rendering for neutral typed documents.

Pure shared application helper — not an agent-callable Tool. Callers map domain
content into ``MarkdownDocument`` / ``MarkdownSection`` and pass the result of
``render_markdown`` elsewhere (for example Drive upload in a later ticket).
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


@dataclass(frozen=True, slots=True)
class MarkdownSection:
    """One section: heading plus optional paragraphs and bullet items."""

    heading: str
    paragraphs: tuple[str, ...] = ()
    bullet_items: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.heading, "heading")
        paragraphs = _require_sequence(self.paragraphs, "paragraphs")
        bullet_items = _require_sequence(self.bullet_items, "bullet_items")
        object.__setattr__(self, "paragraphs", tuple(paragraphs))
        object.__setattr__(self, "bullet_items", tuple(bullet_items))
        for index, paragraph in enumerate(self.paragraphs):
            _require_string(paragraph, f"paragraphs[{index}]")
        for index, item in enumerate(self.bullet_items):
            _require_text(item, f"bullet_items[{index}]")


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
        blocks.append(f"## {_field_text(section.heading)}")
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
    return "\n\n".join(blocks) + "\n"
