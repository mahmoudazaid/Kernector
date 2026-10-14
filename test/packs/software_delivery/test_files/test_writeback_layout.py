"""Seam: ``parse_test_file_layout`` source locations for write-back (#399)."""

from __future__ import annotations

from dataclasses import asdict

from packs.software_delivery.test_files.layout import TagRow
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.test_files.parser import (
    parse_test_file,
    parse_test_file_layout,
)

TAGS = TestFileTagConfig(test_marker="XRay", story_marker="Story", manual_tags=("manual",))


def _text(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_robot_layout_reports_header_boundary_tag_rows_and_default_tags() -> None:
    text = _text(
        "*** Settings ***",
        "Default Tags    smoke",
        "...    ABC-1",
        "",
        "*** Test Cases ***",
        "Scenario: First    Given inline",
        "  [TAGS]    a    # first note",
        "    # standalone",
        "    ...    b    XRay ABC-2  # second note",
        "    When it runs",
        "Scenario: Second",
        "\tThen nothing",
    )

    parsed, layout = parse_test_file_layout("t.robot", text, TAGS)

    assert parsed == parse_test_file("t.robot", text, TAGS)
    assert layout.default_tags == ("smoke", "ABC-1")
    first, second = layout.scenarios
    assert (first.line, first.end_line, first.header_pipe) == (6, 10, False)
    assert first.body_indent == "  "
    assert first.tag_rows == (
        TagRow(line=7, name="[TAGS]", cells=("a",), comment="# first note", indent="  "),
        TagRow(
            line=9,
            name="...",
            cells=("b", "XRay ABC-2"),
            comment="# second note",
            indent="    ",
        ),
    )
    assert (second.line, second.end_line, second.tag_rows, second.body_indent) == (
        11,
        12,
        (),
        "\t",
    )


def test_robot_layout_flags_pipe_rows() -> None:
    text = _text(
        "| *** Test Cases *** |",
        "| Scenario: Pipe |",
        "|    | [Tags] | a |",
        "|    | Given x |",
    )

    _parsed, layout = parse_test_file_layout("t.robot", text, TAGS)

    [scenario] = layout.scenarios
    assert scenario.header_pipe is True
    assert [(row.line, row.pipe, row.cells) for row in scenario.tag_rows] == [(3, True, ("a",))]


def test_gherkin_layout_reports_scenario_tag_lines_but_not_feature_or_examples_tags() -> None:
    text = _text(
        "@Story:ABC-1",
        "Feature: F",
        "",
        "  @smoke @XRay:ABC-2",
        "  # a comment line",
        "  @slow # trailing",
        "  Example: One",
        "    Given x",
        "",
        "  Scenario Outline: Two",
        "    Given <a>",
        "    @fast",
        "    Examples: E",
        "      | a |",
        "      | 1 |",
    )

    parsed, layout = parse_test_file_layout("f.feature", text, TAGS)

    assert parsed == parse_test_file("f.feature", text, TAGS)
    assert layout.default_tags == ()
    one, two = layout.scenarios
    assert (one.line, one.header_indent) == (7, "  ")
    assert one.tag_rows == (
        TagRow(line=4, name="", cells=("smoke", "XRay:ABC-2"), comment=None, indent="  "),
        TagRow(line=6, name="", cells=("slow",), comment="# trailing", indent="  "),
    )
    assert (two.line, two.tag_rows) == (10, ())


def test_layout_does_not_change_the_preview_payload() -> None:
    text = _text("*** Test Cases ***", "Scenario: A", "    [Tags]    x", "    Given y")

    parsed, _layout = parse_test_file_layout("t.robot", text, TAGS)

    assert asdict(parsed) == asdict(parse_test_file("t.robot", text, TAGS))
