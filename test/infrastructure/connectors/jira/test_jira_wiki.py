"""Jira wiki markup to Markdown; expected values are hand-written literals."""

from __future__ import annotations

import pytest

from infrastructure.connectors.jira.wiki import wiki_to_markdown


@pytest.mark.parametrize("raw", [None, 5, {"type": "doc"}, ["h1. x"]])
def test_non_string_input_renders_empty(raw: object) -> None:
    assert wiki_to_markdown(raw) == ""


def test_headings_h1_to_h6() -> None:
    raw = "h1. One\nh2. Two\nh3. Three\nh4. Four\nh5. Five\nh6. Six"

    assert wiki_to_markdown(raw) == (
        "# One\n\n## Two\n\n### Three\n\n#### Four\n\n##### Five\n\n###### Six"
    )


def test_unknown_heading_level_stays_literal() -> None:
    assert wiki_to_markdown("h7. Seven") == "h7. Seven"


def test_paragraph_lines_and_blank_lines_are_kept() -> None:
    assert wiki_to_markdown("  First line\nsecond line\n\n\n\nNext  ") == (
        "First line\nsecond line\n\nNext"
    )


def test_nested_bullet_lists() -> None:
    assert wiki_to_markdown("* a\n** b\n*** c\n* d") == "- a\n  - b\n    - c\n- d"


def test_nested_numbered_lists() -> None:
    assert wiki_to_markdown("# one\n## two\n# three") == "1. one\n   1. two\n1. three"


def test_mixed_list_nesting_aligns_to_the_parent_marker() -> None:
    assert wiki_to_markdown("# step\n#* note\n#*# sub") == (
        "1. step\n   - note\n     1. sub"
    )


def test_list_is_separated_from_surrounding_paragraphs() -> None:
    assert wiki_to_markdown("Intro\n* a\n* b\nOutro") == "Intro\n\n- a\n- b\n\nOutro"


def test_list_depth_is_capped() -> None:
    assert wiki_to_markdown("********* deep") == "          - deep"


def test_emphasis_at_line_start_is_not_a_list() -> None:
    assert wiki_to_markdown("*bold* start") == "**bold** start"


def test_code_block_with_language_keeps_content_verbatim() -> None:
    raw = "Before\n{code:java}\nint x = *1*; // [a|b]\n{code}\nAfter"

    assert wiki_to_markdown(raw) == (
        "Before\n\n```java\nint x = *1*; // [a|b]\n```\n\nAfter"
    )


def test_code_block_without_language() -> None:
    assert wiki_to_markdown("{code}\n  indented\n{code}") == "```\n  indented\n```"


def test_code_block_language_parameter() -> None:
    raw = "{code:title=A.java|language=java}\nclass A {}\n{code}"

    assert wiki_to_markdown(raw) == "```java\nclass A {}\n```"


def test_noformat_block_is_not_transformed() -> None:
    raw = "{noformat}\n*raw* _text_ [x|https://e.x]\nh1. no\n{noformat}"

    assert wiki_to_markdown(raw) == "```\n*raw* _text_ [x|https://e.x]\nh1. no\n```"


def test_single_line_code_block() -> None:
    assert wiki_to_markdown("{code}a = 1{code}") == "```\na = 1\n```"


def test_fence_grows_when_content_contains_backticks() -> None:
    raw = "{noformat}\n```\nnested\n```\n{noformat}"

    assert wiki_to_markdown(raw) == "````\n```\nnested\n```\n````"


def test_table_with_header_row() -> None:
    raw = "||Key||Status||\n|KAN-1|Done|\n|KAN-2|In review|"

    assert wiki_to_markdown(raw) == (
        "| Key | Status |\n| --- | --- |\n| KAN-1 | Done |\n| KAN-2 | In review |"
    )


def test_table_without_header_uses_the_first_row() -> None:
    assert wiki_to_markdown("|a|b|\n|c|d|") == "| a | b |\n| --- | --- |\n| c | d |"


def test_table_cells_keep_link_pipes_and_short_rows_are_padded() -> None:
    raw = "||Name||Link||\n|docs|[guide|https://e.x/g]|\n|only|"

    assert wiki_to_markdown(raw) == (
        "| Name | Link |\n| --- | --- |\n| docs | [guide](https://e.x/g) |\n| only |  |"
    )


def test_titled_link() -> None:
    assert wiki_to_markdown("See [docs|https://x.example/a?b=1] now") == (
        "See [docs](https://x.example/a?b=1) now"
    )


def test_bare_link_and_mailto() -> None:
    assert wiki_to_markdown("[https://x.example] or [mail|mailto:ops@x.example]") == (
        "<https://x.example> or [mail](mailto:ops@x.example)"
    )


def test_mention() -> None:
    assert wiki_to_markdown("[~jdoe] please check") == "@jdoe please check"


def test_bold_and_italic() -> None:
    assert wiki_to_markdown("a *bold* and _it_ word") == "a **bold** and *it* word"


def test_word_internal_markers_are_not_emphasis() -> None:
    assert wiki_to_markdown("snake_case_name and 2*3*4") == "snake_case_name and 2*3*4"


def test_monospace() -> None:
    assert wiki_to_markdown("run {{make *all*}} first") == "run `make *all*` first"


def test_inline_markup_in_headings_and_list_items() -> None:
    assert wiki_to_markdown("h2. *Fix* [KAN-1|https://j.x/browse/KAN-1]\n* _note_") == (
        "## **Fix** [KAN-1](https://j.x/browse/KAN-1)\n\n- *note*"
    )


def test_unterminated_code_block_closes_at_end_of_input() -> None:
    assert wiki_to_markdown("{code:python}\nx = 1\n*still code*") == (
        "```python\nx = 1\n*still code*\n```"
    )


def test_unterminated_noformat_closes_at_end_of_input() -> None:
    assert wiki_to_markdown("Intro\n{noformat}\n[x|y]") == "Intro\n\n```\n[x|y]\n```"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "vbscript:msgbox",
        "//evil.example",
    ],
)
def test_unsafe_link_targets_render_as_plain_text(url: str) -> None:
    assert wiki_to_markdown(f"[click|{url}] here") == "click here"


def test_unsafe_bare_link_stays_literal() -> None:
    assert wiki_to_markdown("[javascript:alert(1)]") == "[javascript:alert(1)]"


def test_html_and_unknown_macros_are_left_as_literal_text() -> None:
    raw = "{html}<script>alert(1)</script>{html}\n{panel:title=Note}Body{panel}"

    assert wiki_to_markdown(raw) == (
        "{html}<script>alert(1)</script>{html}\n{panel:title=Note}Body{panel}"
    )


def test_unbalanced_inline_markers_stay_literal() -> None:
    assert wiki_to_markdown("*open [no close {{mono _half") == "*open [no close {{mono _half"


def test_pathological_input_completes_quickly() -> None:
    import time

    raw = "*" * 10_000 + "[" * 10_000 + "_a" * 5_000 + "{{" * 5_000 + "|" * 5_000
    started = time.perf_counter()

    rendered = wiki_to_markdown(raw)

    assert time.perf_counter() - started < 1.0
    assert isinstance(rendered, str)
