"""Seam: ``rewrite_file`` text fidelity, diff and parser round-trip (#399)."""

from __future__ import annotations

import pytest

from packs.software_delivery.test_files.models import TestFileScenario, TestFileTagConfig
from packs.software_delivery.test_files.parser import parse_test_file
from packs.software_delivery.test_files.writeback import rewrite_file

TAGS = TestFileTagConfig(test_marker="XRay", story_marker="Story", manual_tags=("manual",))


def test_crlf_endings_are_kept_and_inserted_lines_use_them() -> None:
    text = "*** Test Cases ***\r\nScenario: Login\r\n    Given x\r\n"

    result = rewrite_file("t.robot", text, {"Login": "ABC-9"}, TAGS)

    assert result.content == (
        "*** Test Cases ***\r\nScenario: Login\r\n    [Tags]    XRay ABC-9\r\n    Given x\r\n"
    )
    assert rewrite_file("t.robot", result.content, {"Login": "ABC-9"}, TAGS).changed is False


def test_bom_is_kept_in_content_and_left_out_of_the_diff() -> None:
    text = "\ufeffFeature: F\n  Scenario: A\n    Given x\n"

    result = rewrite_file("f.feature", text, {"A": "ABC-9"}, TAGS)

    assert result.content == "\ufeffFeature: F\n  @XRay:ABC-9\n  Scenario: A\n    Given x\n"
    assert "\ufeff" not in result.diff


def test_missing_final_newline_stays_missing_and_is_marked_in_the_diff() -> None:
    text = "*** Test Cases ***\nScenario: Login"

    result = rewrite_file("t.robot", text, {"Login": "ABC-9"}, TAGS)

    assert result.content == "*** Test Cases ***\nScenario: Login\n    [Tags]    XRay ABC-9"
    assert result.diff == (
        "--- a/t.robot\n"
        "+++ b/t.robot\n"
        "@@ -1,2 +1,3 @@\n"
        " *** Test Cases ***\n"
        "-Scenario: Login\n"
        "\\ No newline at end of file\n"
        "+Scenario: Login\n"
        "+    [Tags]    XRay ABC-9\n"
        "\\ No newline at end of file\n"
    )


def test_unchanged_last_line_without_newline_is_marked_as_context() -> None:
    text = "Feature: F\n  Scenario: A\n    Given x"

    result = rewrite_file("f.feature", text, {"A": "ABC-9"}, TAGS)

    assert result.content == "Feature: F\n  @XRay:ABC-9\n  Scenario: A\n    Given x"
    assert result.diff == (
        "--- a/f.feature\n"
        "+++ b/f.feature\n"
        "@@ -1,3 +1,4 @@\n"
        " Feature: F\n"
        "+  @XRay:ABC-9\n"
        "   Scenario: A\n"
        "     Given x\n"
        "\\ No newline at end of file\n"
    )


ROBOT = (
    "*** Settings ***\n"
    "Test Tags    regression\n"
    "Default Tags    manual    Story ABC-1\n"
    "\n"
    "*** Test Cases ***\n"
    "Scenario: Mapped untagged\n"
    "    Given a    arg\n"
    "Scenario: Mapped tagged\n"
    "    [Tags]    smoke    XRay ABC-2\n"
    "    ...    ABC-3\n"
    "    When b\n"
    "Scenario: Unmapped\n"
    "    [Tags]    XRay ABC-4    # keep me\n"
    "    Then c\n"
)
FEATURE = (
    "@Story:ABC-1\n"
    "Feature: F\n"
    "  Background:\n"
    "    Given setup\n"
    "\n"
    "  @manual\n"
    "  Scenario: Mapped untagged\n"
    "    Given a\n"
    "      | x |\n"
    "\n"
    "  @XRay=ABC-2 @fast\n"
    "  Scenario Outline: Mapped tagged <v>\n"
    '    When b\n      """\n      @not-a-tag\n      """\n'
    "    @data\n"
    "    Examples:\n"
    "      | v |\n"
    "      | 1 |\n"
    "\n"
    "  # unmapped below\n"
    "  @XRay:ABC-4\n"
    "  Scenario: Unmapped\n"
    "    Then c\n"
)


def _same_except_xray(before: TestFileScenario, after: TestFileScenario) -> None:
    assert (after.summary, after.keyword, after.kind, after.outline) == (
        before.summary,
        before.keyword,
        before.kind,
        before.outline,
    )
    assert [(s.keyword, s.text, s.arguments) for s in after.steps] == [
        (s.keyword, s.text, s.arguments) for s in before.steps
    ]
    assert len(after.examples) == len(before.examples)
    assert after.story_key == before.story_key
    assert set(after.tags.effective_plain) == set(before.tags.effective_plain)


@pytest.mark.parametrize(
    ("path", "text", "unmapped"),
    [
        ("t.robot", ROBOT, "Scenario: Unmapped\n    [Tags]    XRay ABC-4    # keep me\n"),
        ("f.feature", FEATURE, "  # unmapped below\n  @XRay:ABC-4\n  Scenario: Unmapped\n"),
    ],
)
def test_rewritten_files_round_trip_through_the_parser(
    path: str, text: str, unmapped: str
) -> None:
    keys = {"Mapped untagged": "ABC-8"}
    keys["Mapped tagged" if path.endswith(".robot") else "Mapped tagged <v>"] = "ABC-9"

    result = rewrite_file(path, text, keys, TAGS)

    before = parse_test_file(path, text, TAGS)
    after = parse_test_file(path, result.content, TAGS)
    assert after.file_tags == before.file_tags
    assert after.story_key == before.story_key
    assert [s.xray_key for s in after.scenarios] == ["ABC-8", "ABC-9", "ABC-4"]
    for old, new in zip(before.scenarios, after.scenarios, strict=True):
        _same_except_xray(old, new)
    assert unmapped in result.content
    assert rewrite_file(path, result.content, keys, TAGS).changed is False
