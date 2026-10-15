"""Seam: ``propose_target`` / ``build_new_path`` (#400)."""

from __future__ import annotations

from domain.test_management.xray import StoryNamingContext
from packs.software_delivery.test_files.models import (
    ParsedTestFile,
    TagRoles,
    TestFileTagConfig,
)
from packs.software_delivery.test_files.parser import parse_test_file
from packs.software_delivery.test_files.pull_target import (
    TargetAmbiguous,
    TargetHit,
    TargetNamingFailed,
    build_new_path,
    propose_target,
    validate_relative_path,
    validate_template,
)

TAGS = TestFileTagConfig("XRay", "Story", ("manual", "scaffold"))


def test_existing_robot_suite_matched_by_default_tags() -> None:
    text = (
        "*** Settings ***\nDefault Tags    Story    ABC-1\n\n"
        "*** Test Cases ***\nScenario: Other\n    [Tags]    manual\n    Given x\n"
    )
    parsed = parse_test_file("suites/login.robot", text, TAGS)
    naming = StoryNamingContext("ABC-1", "Login", "absent")

    hit = propose_target(
        story_key="ABC-1",
        fmt="robot",
        inventory=[parsed],
        naming=naming,
        template="{story_key}_{story_summary}",
    )

    assert hit == TargetHit("existing", "suites/login.robot")


def test_multiple_matching_files_are_ambiguous() -> None:
    a = parse_test_file(
        "a.robot",
        "*** Settings ***\nDefault Tags    Story ABC-1\n\n*** Test Cases ***\n"
        "Scenario: A\n    Given x\n",
        TAGS,
    )
    b = parse_test_file(
        "b.robot",
        "*** Settings ***\nDefault Tags    Story ABC-1\n\n*** Test Cases ***\n"
        "Scenario: B\n    Given y\n",
        TAGS,
    )
    naming = StoryNamingContext("ABC-1", "Login", "absent")

    result = propose_target(
        story_key="ABC-1",
        fmt="robot",
        inventory=[a, b],
        naming=naming,
        template="{story_key}",
    )

    assert isinstance(result, TargetAmbiguous)


def test_epic_failed_is_naming_failed_not_absent() -> None:
    naming = StoryNamingContext("ABC-1", "Login", "failed")
    result = build_new_path(naming, "{epic_summary}__{story_summary}", ".robot")
    assert result == TargetNamingFailed("epic_lookup_failed")


def test_path_collision_against_inventory() -> None:
    empty = ParsedTestFile(
        path="Login.robot",
        format="robot",
        file_tags=TagRoles(),
        story_key=None,
        story_candidates=(),
        background=None,
        scenarios=(),
    )
    naming = StoryNamingContext("ABC-1", "Login", "absent")
    result = propose_target(
        story_key="ABC-1",
        fmt="robot",
        inventory=[empty],
        naming=naming,
        template="{story_summary}",
    )
    assert isinstance(result, TargetNamingFailed)
    assert result.reason == "path_collision"


def test_new_path_reused_by_same_story_but_collides_for_another() -> None:
    naming = StoryNamingContext("ABC-1", "Login", "absent")

    same = propose_target(
        story_key="ABC-1",
        fmt="robot",
        inventory=[],
        naming=naming,
        template="{story_summary}",
        proposed_paths={"Login.robot": "ABC-1"},
    )
    other = propose_target(
        story_key="ABC-1",
        fmt="robot",
        inventory=[],
        naming=naming,
        template="{story_summary}",
        proposed_paths={"Login.robot": "ABC-2"},
    )

    assert same == TargetHit("new", "Login.robot")
    assert other == TargetNamingFailed("path_collision")


def test_feature_file_not_matched_by_scenario_story_tag_only() -> None:
    parsed = parse_test_file(
        "s.feature",
        "Feature: Login\n\n  @Story:ABC-1 @XRay:QA-1\n  Scenario: Existing\n    Given x\n",
        TAGS,
    )
    naming = StoryNamingContext("ABC-1", "Login", "absent")

    result = propose_target(
        story_key="ABC-1",
        fmt="feature",
        inventory=[parsed],
        naming=naming,
        template="{story_key}",
    )

    assert result == TargetHit("new", "ABC-1.feature")


def test_ellipsis_in_story_summary_is_not_traversal() -> None:
    for summary in ("Retry... then fail", "Upgrade v1..v2 data"):
        naming = StoryNamingContext("ABC-1", summary, "absent")
        built = build_new_path(naming, "{story_summary}", ".robot")
        assert isinstance(built, str) and built.endswith(".robot")


def test_validate_relative_path_rejects_traversal() -> None:
    assert isinstance(validate_relative_path("../x.robot"), TargetNamingFailed)
    assert validate_relative_path("dir/suite", extension=".robot") == "dir/suite.robot"


def test_validate_template_rejects_unknown_placeholders() -> None:
    assert validate_template("{story_key}_{nope}") == "unknown_template_placeholder"
    assert validate_template("{story_key}_{story_summary}") is None
