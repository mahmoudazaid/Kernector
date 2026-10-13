"""Seam: ``parse_test_file`` tag roles for both syntaxes (#396)."""

from __future__ import annotations

import pytest

from packs.software_delivery.errors import TestFileErrorReason, TestFileValidationError
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.test_files.parser import parse_test_file

TAGS = TestFileTagConfig(
    test_marker="XRay", story_marker="Story", manual_tags=("manual", "scaffold")
)


def _robot_scenario_tags(*cells: str, tags: TestFileTagConfig = TAGS):
    text = "*** Test Cases ***\nScenario: S\n    [Tags]    " + "    ".join(cells) + "\n"
    [scenario] = parse_test_file("t.robot", text, tags).scenarios
    return scenario


def test_robot_composite_tags_split_into_marker_and_key_in_either_order() -> None:
    scenario = _robot_scenario_tags("xray ABC-1", "Story=ABC-2", "ABC-3", "env:prod", "owner=qa")

    local = scenario.tags.local
    assert (local.xray_key, local.story_key) == ("ABC-1", "ABC-2")
    assert local.candidate_keys == ("ABC-3",)
    assert local.plain == ("env:prod", "owner=qa")
    assert (scenario.xray_key, scenario.story_key) == ("ABC-1", "ABC-2")

    reversed_order = _robot_scenario_tags("ABC-1 XRay", "ABC-2: story")
    assert (reversed_order.xray_key, reversed_order.story_key) == ("ABC-1", "ABC-2")


def test_marker_names_come_from_the_configuration() -> None:
    custom = TestFileTagConfig(test_marker="TestKey", story_marker="Req", manual_tags=("todo",))

    scenario = _robot_scenario_tags("TestKey ABC-1", "Req ABC-2", "XRay ABC-3", "todo", tags=custom)

    assert (scenario.xray_key, scenario.story_key) == ("ABC-1", "ABC-2")
    assert scenario.tags.local.plain == ("XRay ABC-3", "todo")
    assert scenario.kind == "manual"


def test_bug_tags_are_plain_tags_without_roles_in_robot() -> None:
    scenario = _robot_scenario_tags("Bug", "Bug ABC-1", "ABC-2 Bug")

    local = scenario.tags.local
    assert local.plain == ("Bug", "Bug ABC-1", "ABC-2 Bug")
    assert (local.xray_key, local.story_key, local.candidate_keys) == (None, None, ())


def _gherkin_scenario_tags(tag_line: str, tags: TestFileTagConfig = TAGS):
    text = f"Feature: F\n\n  {tag_line}\n  Scenario: S\n    Given something\n"
    [scenario] = parse_test_file("t.feature", text, tags).scenarios
    return scenario


def test_gherkin_tag_lines_hold_several_tags_and_a_trailing_comment() -> None:
    scenario = _gherkin_scenario_tags("@smoke   @XRay:ABC-1\t@Story=ABC-2 @ABC-3 # @ignored")

    local = scenario.tags.local
    assert (local.xray_key, local.story_key) == ("ABC-1", "ABC-2")
    assert local.candidate_keys == ("ABC-3",)
    assert local.plain == ("smoke",)


def test_gherkin_separate_marker_tag_is_not_a_composite_and_other_colons_stay_whole() -> None:
    scenario = _gherkin_scenario_tags("@XRay @ABC-1 @env:prod @owner=qa @ABC-2:xray")

    local = scenario.tags.local
    assert local.plain == ("XRay", "env:prod", "owner=qa")
    assert local.candidate_keys == ("ABC-1",)
    assert local.xray_key == "ABC-2"


def test_gherkin_space_inside_a_tag_is_a_malformed_tag_line() -> None:
    with pytest.raises(TestFileValidationError) as caught:
        _gherkin_scenario_tags("@XRay ABC-1")

    assert (caught.value.path, caught.value.line) == ("t.feature", 3)
    assert caught.value.reason is TestFileErrorReason.MALFORMED_TAG


def test_bug_tags_are_plain_tags_without_roles_in_gherkin() -> None:
    scenario = _gherkin_scenario_tags("@Bug @Bug:ABC-9 @ABC-8=Bug")

    local = scenario.tags.local
    assert local.plain == ("Bug", "Bug:ABC-9", "ABC-8=Bug")
    assert (local.xray_key, local.story_key, local.candidate_keys) == (None, None, ())
