"""Seam: ``parse_test_file`` rejects malformed or unsupported input with file and line."""

from __future__ import annotations

import pytest

from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.test_files.parser import parse_test_file

TAGS = TestFileTagConfig(
    test_marker="XRay", story_marker="Story", manual_tags=("manual", "scaffold")
)


def _lines(*lines: str) -> str:
    return "\n".join(lines) + "\n"


GHERKIN_CASES = [
    ("missing feature", _lines("# c", "Scenario: S", "  Given x"), 2, Reason.MISSING_FEATURE),
    ("missing feature at eof", _lines("# only a comment", "@tag"), 2, Reason.DANGLING_TAGS),
    ("empty file", _lines("# only a comment"), None, Reason.MISSING_FEATURE),
    ("second feature", _lines("Feature: A", "Feature: B"), 2, Reason.DUPLICATE_FEATURE),
    (
        "orphan table",
        _lines("Feature: F", "  Scenario: S", "    Given x", "    Something", "    | a |"),
        4,
        Reason.UNEXPECTED_LINE,
    ),
    ("table before steps", _lines("Feature: F", "  Scenario: S", "    | a |"), 3, Reason.ORPHAN_TABLE),
    (
        "orphan doc string",
        _lines("Feature: F", "  Scenario: S", '    """', '    """'),
        3,
        Reason.ORPHAN_DOC_STRING,
    ),
    (
        "doc string after table",
        _lines("Feature: F", "  Scenario: S", "    Given x", "      | a |", '      """', '      """'),
        5,
        Reason.ORPHAN_DOC_STRING,
    ),
    (
        "unclosed doc string",
        _lines("Feature: F", "  Scenario: S", "    Given x", '      """', "      text"),
        4,
        Reason.UNCLOSED_DOC_STRING,
    ),
    (
        "examples outside outline",
        _lines("Feature: F", "  Scenario: S", "    Given x", "    Examples:", "      | a |"),
        4,
        Reason.EXAMPLES_OUTSIDE_OUTLINE,
    ),
    (
        "outline without examples",
        _lines("Feature: F", "  Scenario Outline: S", "    Given <a>"),
        2,
        Reason.OUTLINE_WITHOUT_EXAMPLES,
    ),
    (
        "examples without data rows",
        _lines("Feature: F", "  Scenario Outline: S", "    Given <a>", "    Examples:", "      | a |"),
        4,
        Reason.EXAMPLES_WITHOUT_ROWS,
    ),
    (
        "examples without table",
        _lines(
            "Feature: F",
            "  Scenario Outline: S",
            "    Given <a>",
            "    Examples:",
            "  Scenario: T",
            "    Given y",
        ),
        4,
        Reason.EXAMPLES_WITHOUT_ROWS,
    ),
    (
        "inconsistent examples width",
        _lines(
            "Feature: F",
            "  Scenario Outline: S",
            "    Given <a>",
            "    Examples:",
            "      | a |",
            "      | 1 | 2 |",
        ),
        6,
        Reason.INCONSISTENT_ROW_WIDTH,
    ),
    (
        "inconsistent step table width",
        _lines("Feature: F", "  Scenario: S", "    Given x", "      | a | b |", "      | 1 |"),
        5,
        Reason.INCONSISTENT_ROW_WIDTH,
    ),
    (
        "unterminated table row",
        _lines("Feature: F", "  Scenario: S", "    Given x", "      | a | b"),
        4,
        Reason.MALFORMED_TABLE_ROW,
    ),
    ("rule", _lines("Feature: F", "  Rule: R", "    Scenario: S"), 2, Reason.UNSUPPORTED_RULE),
    (
        "second background",
        _lines("Feature: F", "  Background:", "    Given x", "  Background:", "    Given y"),
        4,
        Reason.DUPLICATE_BACKGROUND,
    ),
    (
        "background after scenario",
        _lines("Feature: F", "  Scenario: S", "    Given x", "  Background:", "    Given y"),
        4,
        Reason.BACKGROUND_AFTER_SCENARIO,
    ),
    (
        "tags before background",
        _lines("Feature: F", "  @t", "  Background:", "    Given y"),
        2,
        Reason.DANGLING_TAGS,
    ),
    (
        "tags before a step",
        _lines("Feature: F", "  Scenario: S", "    @t", "    Given y"),
        3,
        Reason.DANGLING_TAGS,
    ),
    (
        "trailing tags",
        _lines("Feature: F", "  Scenario: S", "    Given y", "  @t"),
        4,
        Reason.DANGLING_TAGS,
    ),
    ("language", _lines("# language: fr", "Fonctionnalité: F"), 1, Reason.UNSUPPORTED_LANGUAGE),
    (
        "step before scenario",
        _lines("Feature: F", "  Given x", "  Scenario: S"),
        2,
        Reason.STEP_OUTSIDE_SCENARIO,
    ),
    (
        "text after steps",
        _lines("Feature: F", "  Scenario: S", "    Given x", "    stray text"),
        4,
        Reason.UNEXPECTED_LINE,
    ),
    (
        "step inside examples",
        _lines(
            "Feature: F",
            "  Scenario Outline: S",
            "    Given <a>",
            "    Examples:",
            "      | a |",
            "      | 1 |",
            "    Then z",
        ),
        7,
        Reason.UNEXPECTED_LINE,
    ),
    ("empty scenario name", _lines("Feature: F", "  Scenario:", "    Given x"), 2, Reason.EMPTY_SCENARIO_NAME),
]


@pytest.mark.parametrize(
    ("text", "line", "reason"),
    [case[1:] for case in GHERKIN_CASES],
    ids=[case[0] for case in GHERKIN_CASES],
)
def test_malformed_gherkin_names_file_and_line(text: str, line: int | None, reason: Reason) -> None:
    with pytest.raises(TestFileValidationError) as caught:
        parse_test_file("features/bad.feature", text, TAGS)

    assert (caught.value.path, caught.value.line, caught.value.reason) == (
        "features/bad.feature",
        line,
        reason,
    )
    location = "features/bad.feature" if line is None else f"features/bad.feature:{line}"
    assert caught.value.safe_message == f"{location}: {reason.value}"


ROBOT_CASES = [
    (
        "empty summary",
        _lines("*** Test Cases ***", "Scenario:", "    Given x"),
        2,
        Reason.EMPTY_SCENARIO_NAME,
    ),
    (
        "leading continuation",
        _lines("*** Test Cases ***", "Scenario: S", "    ...    orphan", "    Given x"),
        3,
        Reason.LEADING_CONTINUATION,
    ),
]


@pytest.mark.parametrize(
    ("text", "line", "reason"),
    [case[1:] for case in ROBOT_CASES],
    ids=[case[0] for case in ROBOT_CASES],
)
def test_malformed_robot_names_file_and_line(text: str, line: int, reason: Reason) -> None:
    with pytest.raises(TestFileValidationError) as caught:
        parse_test_file("tests/bad.robot", text, TAGS)

    assert (caught.value.line, caught.value.reason) == (line, reason)


def test_unsupported_extension_is_rejected_without_a_line() -> None:
    with pytest.raises(TestFileValidationError) as caught:
        parse_test_file("tests/notes.txt", "Scenario: S\n", TAGS)

    assert (caught.value.path, caught.value.line) == ("tests/notes.txt", None)
    assert caught.value.reason is Reason.UNSUPPORTED_EXTENSION


def test_extensions_match_case_insensitively() -> None:
    robot = parse_test_file("T.ROBOT", "*** Test Cases ***\nScenario: S\n    Given x\n", TAGS)
    feature = parse_test_file("F.Feature", "Feature: F\n  Scenario: S\n    Given x\n", TAGS)

    assert (robot.format, feature.format) == ("robot", "gherkin")
