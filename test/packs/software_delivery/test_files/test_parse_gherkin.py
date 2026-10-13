"""Seam: ``parse_test_file`` on Gherkin ``.feature`` content (#396)."""

from __future__ import annotations

from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.test_files.parser import parse_test_file

TAGS = TestFileTagConfig(
    test_marker="XRay", story_marker="Story", manual_tags=("manual", "scaffold")
)


def _feature(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_scenarios_keep_names_as_written_with_steps_and_scenario_tags() -> None:
    text = _feature(
        "# a comment",
        "@ABC-123",
        "Feature: [ABC-123] Short story title",
        "  Free description of the feature.",
        "",
        "  @XRay:ABC-7",
        "  Scenario: 1- First behavior",
        "    Given a user",
        "    When they log in",
        "    * they see <things>",
        "    Then the dashboard is shown",
        "",
        "  Example: 2- Second behavior",
        "    Given another user",
    )

    parsed = parse_test_file("features/login.feature", text, TAGS)

    assert parsed.format == "gherkin"
    assert parsed.story_key == "ABC-123"
    first, second = parsed.scenarios
    assert (first.line, first.keyword, first.summary) == (7, "Scenario", "1- First behavior")
    assert [(s.line, s.keyword, s.text) for s in first.steps] == [
        (8, "Given", "Given a user"),
        (9, "When", "When they log in"),
        (10, "*", "* they see <things>"),
        (11, "Then", "Then the dashboard is shown"),
    ]
    assert (first.xray_key, first.story_key, first.kind) == ("ABC-7", "ABC-123", "cucumber")
    assert (second.keyword, second.summary, second.xray_key) == ("Example", "2- Second behavior", None)


def _story(*header: str):
    parsed = parse_test_file(
        "f.feature", _feature(*header, "  Scenario: S", "    Given x"), TAGS
    )
    return parsed.story_key, parsed.story_candidates


def test_a_leading_bom_is_ignored() -> None:
    parsed = parse_test_file(
        "f.feature", "\ufeff" + _feature("Feature: F", "  Scenario: A", "    Given x"), TAGS
    )

    assert [scenario.summary for scenario in parsed.scenarios] == ["A"]


def test_file_story_prefers_the_tag_then_the_title_bracket_and_never_guesses() -> None:
    assert _story("@ABC-1", "Feature: [ABC-2] Title") == ("ABC-1", ("ABC-1",))
    assert _story("Feature: [ABC-2] Title") == ("ABC-2", ())
    assert _story("@Story:ABC-3 @ABC-4", "Feature: [ABC-2] Title") == ("ABC-3", ("ABC-4",))
    assert _story("@ABC-1 @ABC-5", "Feature: [ABC-2] Title") == (None, ("ABC-1", "ABC-5"))
    assert _story("@smoke", "Feature: No key") == (None, ())


def test_background_steps_keep_their_tables_and_doc_strings() -> None:
    text = _feature(
        "Feature: F",
        "  Background: Shared setup",
        "    Given users exist",
        "      | name  | role \\| scope |",
        "      | alice | admin         |",
        "    And a payload",
        '      """json',
        '      {"a": 1}',
        "      # not a comment",
        "      Scenario: not a keyword",
        "      | not | a table |",
        '      """',
        "  Scenario: S",
        "    Given x",
        "      ```",
        "        indented line",
        "      ```",
    )

    parsed = parse_test_file("f.feature", text, TAGS)

    background = parsed.background
    assert background is not None
    assert (background.line, background.name) == (2, "Shared setup")
    users, payload = background.steps
    assert users.data_table is not None
    assert [(row.line, row.cells) for row in users.data_table.rows] == [
        (4, ("name", "role \\| scope")),
        (5, ("alice", "admin")),
    ]
    assert payload.doc_string is not None
    assert (payload.doc_string.line, payload.doc_string.delimiter) == (7, '"""')
    assert payload.doc_string.media_type == "json"
    assert payload.doc_string.lines == (
        '      {"a": 1}',
        "      # not a comment",
        "      Scenario: not a keyword",
        "      | not | a table |",
    )
    [scenario] = parsed.scenarios
    [step] = scenario.steps
    assert step.doc_string is not None
    assert (step.doc_string.delimiter, step.doc_string.media_type) == ("```", "")
    assert step.doc_string.lines == ("        indented line",)


def test_scenario_outline_is_one_spec_with_placeholders_and_typed_examples() -> None:
    text = _feature(
        "Feature: F",
        "  Scenario Outline: Login as <role>",
        "    Given a <role> user",
        "    Then they see <page>",
        "",
        "    @fast",
        "    Examples: Admins",
        "      | role  | page      |",
        "      | admin | dashboard |",
        "      | root  | console   |",
        "",
        "    @slow @nightly",
        "    Scenarios:",
        "      | role  | page |",
        "      | guest | home |",
    )

    [outline] = parse_test_file("f.feature", text, TAGS).scenarios

    assert (outline.keyword, outline.outline, outline.summary) == (
        "Scenario Outline",
        True,
        "Login as <role>",
    )
    assert [step.text for step in outline.steps] == [
        "Given a <role> user",
        "Then they see <page>",
    ]
    admins, guests = outline.examples
    assert (admins.line, admins.keyword, admins.name, admins.tags) == (
        7,
        "Examples",
        "Admins",
        ("fast",),
    )
    assert (admins.header.line, admins.header.cells) == (8, ("role", "page"))
    assert [(row.line, row.cells) for row in admins.rows] == [
        (9, ("admin", "dashboard")),
        (10, ("root", "console")),
    ]
    assert (guests.keyword, guests.name, guests.tags) == ("Scenarios", "", ("slow", "nightly"))
    assert [row.cells for row in guests.rows] == [("guest", "home")]
    assert outline.tags.local.plain == ()


ROUND_TRIP = _feature(
    "@ABC-1",
    "Feature: Round trip",
    "  Background:",
    "    Given a table",
    "      | a | b |",
    "      | 1 | 2 |",
    "",
    "  Scenario Outline: Uses <x>",
    "    Given a doc",
    '      """text/plain',
    "      line one",
    "",
    "      | kept |",
    '      """',
    "    When <x> happens",
    "      | c | d |",
    "      | 3 | 4 |",
    "    Examples: first",
    "      | x |",
    "      | 5 |",
    "      | 6 |",
    "    Examples: second",
    "      | x |",
    "      | 7 |",
)


def test_round_trip_keeps_every_table_row_doc_string_line_and_examples_row() -> None:
    parsed = parse_test_file("f.feature", ROUND_TRIP, TAGS)
    lines = ROUND_TRIP.splitlines()

    assert parsed.background is not None
    [outline] = parsed.scenarios
    steps = (*parsed.background.steps, *outline.steps)
    table_rows = [row for step in steps if step.data_table for row in step.data_table.rows]
    example_rows = [
        row for block in outline.examples for row in (block.header, *block.rows)
    ]
    doc_lines = [
        (step.doc_string.line, step.doc_string.lines) for step in steps if step.doc_string
    ]

    source_rows = [
        number
        for number, line in enumerate(lines, start=1)
        if line.strip().startswith("|") and number not in range(11, 14)
    ]
    assert sorted(row.line for row in (*table_rows, *example_rows)) == source_rows
    for row in (*table_rows, *example_rows):
        assert lines[row.line - 1].strip() == "| " + " | ".join(row.cells) + " |"
    assert doc_lines == [(10, tuple(lines[10:13]))]
