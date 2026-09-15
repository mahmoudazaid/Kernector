"""Public-seam tests for the shared deterministic Markdown renderer."""

import pytest

from application.errors import ApplicationValidationError
from application.markdown import MarkdownDocument, MarkdownSection, render_markdown

BLANK = ["", "   ", "\n"]


@pytest.mark.parametrize("blank", BLANK)
def test_markdown_document_rejects_blank_title(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="title"):
        MarkdownDocument(title=blank)


@pytest.mark.parametrize("blank", BLANK)
def test_markdown_section_rejects_blank_heading(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="heading"):
        MarkdownSection(heading=blank)


@pytest.mark.parametrize("blank", BLANK)
def test_markdown_section_rejects_blank_bullet_item(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="bullet_items"):
        MarkdownSection(heading="Cases", bullet_items=(blank,))


@pytest.mark.parametrize("bad", [None, 42, True])
def test_markdown_section_rejects_non_string_paragraph(bad: object) -> None:
    with pytest.raises(ApplicationValidationError, match="paragraphs"):
        MarkdownSection(heading="Notes", paragraphs=(bad,))  # type: ignore[arg-type]


def test_markdown_section_allows_blank_paragraph_strings() -> None:
    section = MarkdownSection(heading="Notes", paragraphs=("", "   "))
    assert section.paragraphs == ("", "   ")


def test_render_markdown_title_only() -> None:
    document = MarkdownDocument(title="Export")
    assert render_markdown(document) == "# Export\n"


def test_render_markdown_title_and_section_heading() -> None:
    document = MarkdownDocument(
        title="Export",
        sections=(MarkdownSection(heading="Selected cases"),),
    )
    assert render_markdown(document) == (
        "# Export\n"
        "\n"
        "## Selected cases\n"
    )


def test_render_markdown_section_paragraphs() -> None:
    document = MarkdownDocument(
        title="Export",
        sections=(
            MarkdownSection(
                heading="Notes",
                paragraphs=("First note.", "Second note."),
            ),
        ),
    )
    assert render_markdown(document) == (
        "# Export\n"
        "\n"
        "## Notes\n"
        "\n"
        "First note\\.\n"
        "\n"
        "Second note\\.\n"
    )


def test_render_markdown_section_bullets() -> None:
    document = MarkdownDocument(
        title="Export",
        sections=(
            MarkdownSection(
                heading="Cases",
                bullet_items=("Login happy path", "Logout clears session"),
            ),
        ),
    )
    assert render_markdown(document) == (
        "# Export\n"
        "\n"
        "## Cases\n"
        "\n"
        "- Login happy path\n"
        "- Logout clears session\n"
    )


def test_render_markdown_preserves_section_order() -> None:
    document = MarkdownDocument(
        title="Export",
        sections=(
            MarkdownSection(heading="Alpha", bullet_items=("a1",)),
            MarkdownSection(heading="Beta", paragraphs=("b para",)),
        ),
    )
    assert render_markdown(document) == (
        "# Export\n"
        "\n"
        "## Alpha\n"
        "\n"
        "- a1\n"
        "\n"
        "## Beta\n"
        "\n"
        "b para\n"
    )


def test_render_markdown_preserves_unicode() -> None:
    document = MarkdownDocument(
        title="Résumé",
        sections=(
            MarkdownSection(
                heading="日本語",
                paragraphs=("café — naïve",),
                bullet_items=("emoji ✅",),
            ),
        ),
    )
    assert render_markdown(document) == (
        "# Résumé\n"
        "\n"
        "## 日本語\n"
        "\n"
        "café — naïve\n"
        "\n"
        "- emoji ✅\n"
    )


def test_render_markdown_no_trailing_spaces_and_one_final_newline() -> None:
    document = MarkdownDocument(
        title="  Trimmed  ",
        sections=(
            MarkdownSection(
                heading="  Heading  ",
                paragraphs=("  para  ",),
                bullet_items=("  item  ",),
            ),
        ),
    )
    rendered = render_markdown(document)
    assert rendered.endswith("\n")
    assert not rendered.endswith("\n\n")
    assert all(not line.endswith(" ") for line in rendered.splitlines())
    assert rendered == (
        "# Trimmed\n"
        "\n"
        "## Heading\n"
        "\n"
        "para\n"
        "\n"
        "- item\n"
    )


def test_render_markdown_escapes_structural_specials() -> None:
    document = MarkdownDocument(
        title="# Spoof *Title*",
        sections=(
            MarkdownSection(
                heading="Link [me](/x) and `code`",
                paragraphs=("Has _emphasis_ and \\ slash",),
                bullet_items=("Item with # hash",),
            ),
        ),
    )
    assert render_markdown(document) == (
        "# \\# Spoof \\*Title\\*\n"
        "\n"
        "## Link \\[me\\](/x) and \\`code\\`\n"
        "\n"
        "Has \\_emphasis\\_ and \\\\ slash\n"
        "\n"
        "- Item with \\# hash\n"
    )


def test_render_markdown_escapes_block_leaders_and_html() -> None:
    document = MarkdownDocument(
        title="Export",
        sections=(
            MarkdownSection(
                heading="Notes",
                paragraphs=(
                    "- fake bullet",
                    "> fake quote",
                    "1. fake ordered",
                    "---",
                    "| a | b |",
                    "<script>alert(1)</script>",
                    "+ plus list",
                ),
            ),
        ),
    )
    assert render_markdown(document) == (
        "# Export\n"
        "\n"
        "## Notes\n"
        "\n"
        "\\- fake bullet\n"
        "\n"
        "\\> fake quote\n"
        "\n"
        "1\\. fake ordered\n"
        "\n"
        "\\-\\-\\-\n"
        "\n"
        "\\| a \\| b \\|\n"
        "\n"
        "\\<script\\>alert(1)\\</script\\>\n"
        "\n"
        "\\+ plus list\n"
    )


def test_render_markdown_normalizes_embedded_line_breaks() -> None:
    document = MarkdownDocument(
        title="One\nTwo",
        sections=(
            MarkdownSection(
                heading="Head\r\nBreak",
                paragraphs=("Para\u2028line",),
                bullet_items=("Bullet\u2029item",),
            ),
        ),
    )
    rendered = render_markdown(document)
    assert "# One Two\n" in rendered
    assert "## Head Break\n" in rendered
    assert "Para line\n" in rendered
    assert "- Bullet item\n" in rendered
    assert rendered.count("\n#") == 1
    assert rendered == (
        "# One Two\n"
        "\n"
        "## Head Break\n"
        "\n"
        "Para line\n"
        "\n"
        "- Bullet item\n"
    )


def test_render_markdown_skips_blank_paragraphs() -> None:
    document = MarkdownDocument(
        title="Export",
        sections=(
            MarkdownSection(
                heading="Notes",
                paragraphs=("Keep me", "   ", "Also keep"),
            ),
        ),
    )
    assert render_markdown(document) == (
        "# Export\n"
        "\n"
        "## Notes\n"
        "\n"
        "Keep me\n"
        "\n"
        "Also keep\n"
    )
