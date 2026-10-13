"""Seam: ``parse_test_file`` inherited vs local roles and key conflicts (#396)."""

from __future__ import annotations

import pytest

from packs.software_delivery.errors import TestFileErrorReason, TestFileValidationError
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.test_files.parser import parse_test_file

TAGS = TestFileTagConfig(
    test_marker="XRay", story_marker="Story", manual_tags=("manual", "scaffold")
)


def _feature(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_scenario_story_overrides_the_file_story_and_feature_plain_tags_are_inherited() -> None:
    text = _feature(
        "@ABC-1 @Manual @team",
        "Feature: F",
        "  @Story:ABC-2 @XRay:ABC-3 @XRay:ABC-3",
        "  Scenario: Override",
        "    Given x",
        "  Scenario: Inherit",
        "    Given x",
    )

    override, inherit = parse_test_file("f.feature", text, TAGS).scenarios

    assert (override.story_key, override.xray_key) == ("ABC-2", "ABC-3")
    assert override.tags.inherited.candidate_keys == ("ABC-1",)
    assert override.tags.inherited.plain == ("Manual", "team")
    assert override.tags.local.story_key == "ABC-2"
    assert (inherit.story_key, inherit.xray_key) == ("ABC-1", None)
    assert inherit.tags.effective_plain == ("Manual", "team")
    assert (override.kind, inherit.kind) == ("manual", "manual")


@pytest.mark.parametrize(
    ("tag_line", "line", "reason"),
    [
        ("@XRay:ABC-1 @XRay=ABC-2", 3, TestFileErrorReason.CONFLICTING_XRAY_KEYS),
        ("@Story:ABC-1 @story:ABC-2", 3, TestFileErrorReason.CONFLICTING_STORY_KEYS),
    ],
)
def test_two_distinct_keys_for_one_role_in_one_scope_are_rejected(
    tag_line: str, line: int, reason: TestFileErrorReason
) -> None:
    text = _feature("Feature: F", "", f"  {tag_line}", "  Scenario: S", "    Given x")

    with pytest.raises(TestFileValidationError) as caught:
        parse_test_file("f.feature", text, TAGS)

    assert (caught.value.line, caught.value.reason) == (line, reason)


def test_two_distinct_robot_xray_keys_report_the_second_tag_line() -> None:
    text = (
        "*** Test Cases ***\nScenario: S\n    [Tags]    XRay ABC-1\n"
        "    [Tags]    XRay ABC-2\n    Given x\n"
    )

    with pytest.raises(TestFileValidationError) as caught:
        parse_test_file("t.robot", text, TAGS)

    assert (caught.value.path, caught.value.line) == ("t.robot", 4)
    assert caught.value.reason is TestFileErrorReason.CONFLICTING_XRAY_KEYS


@pytest.mark.parametrize(
    ("path", "text", "line"),
    [
        ("f.feature", "@XRay:ABC-1\nFeature: F\n  Scenario: S\n    Given x\n", 1),
        (
            "t.robot",
            "*** Settings ***\nDefault Tags    XRay ABC-1\n"
            "*** Test Cases ***\nScenario: S\n    Given x\n",
            2,
        ),
    ],
)
def test_a_file_level_xray_key_is_rejected(path: str, text: str, line: int) -> None:
    with pytest.raises(TestFileValidationError) as caught:
        parse_test_file(path, text, TAGS)

    assert (caught.value.line, caught.value.reason) == (
        line,
        TestFileErrorReason.FILE_LEVEL_XRAY_KEY,
    )
