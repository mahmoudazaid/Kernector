"""Seam: ``apply_pull_edits`` / ``insert_scenario`` (#400)."""

from __future__ import annotations

from packs.software_delivery.test_files.from_xray import ScenarioRender
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.test_files.parser import parse_test_file
from packs.software_delivery.test_files.pull_apply import (
    AddEdit,
    BackfillEdit,
    apply_pull_edits,
    insert_scenario,
)

TAGS = TestFileTagConfig("XRay", "Story", ("manual", "scaffold"))


def test_robot_insert_before_keywords_section() -> None:
    text = (
        "*** Settings ***\nDefault Tags    Story    ABC-1\n\n"
        "*** Test Cases ***\nScenario: Existing\n    Given a\n\n"
        "*** Keywords ***\nHelper\n    Log    hi\n"
    )
    render = ScenarioRender(
        "robot",
        "Pulled",
        "QA-7",
        "Scenario: Pulled\n    [Tags]    XRay:QA-7\n    Given b",
    )

    out = insert_scenario("t.robot", text, render, TAGS)

    assert out.index("Scenario: Pulled") < out.index("*** Keywords ***")
    assert "Given a" in out
    assert "Helper" in out


def test_aggregate_backfill_and_add_one_diff() -> None:
    text = (
        "*** Settings ***\nDefault Tags    Story    ABC-1\n\n"
        "*** Test Cases ***\nScenario: Untagged\n    [Tags]    manual\n    Given old\n"
    )
    parsed = parse_test_file("t.robot", text, TAGS)
    render = ScenarioRender(
        "robot",
        "Added",
        "QA-8",
        "Scenario: Added\n    [Tags]    XRay:QA-8\n    Given new",
    )

    [proposal] = apply_pull_edits(
        {"t.robot": text},
        adds=[AddEdit("t.robot", render)],
        backfills=[BackfillEdit("t.robot", "Untagged", "QA-7")],
        new_files={},
        tags=TAGS,
        parsed_by_path={"t.robot": parsed},
    )

    assert proposal.changed
    assert "QA-7" in proposal.content
    assert "Scenario: Added" in proposal.content
    assert "Given old" in proposal.content
    assert proposal.diff
