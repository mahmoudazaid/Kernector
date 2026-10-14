"""``XrayTestPatch`` only admits sparse, self-consistent updates (#398)."""

from __future__ import annotations

import pytest

from domain.test_management.xray import (
    CucumberDefinition,
    IssueLinkRef,
    ManualDefinition,
    XrayTestPatch,
    XrayTestStep,
)

STEPS = ManualDefinition((XrayTestStep(action="Given a"),))


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"key": "", "summary": "x"},
        {"issue_id": "", "summary": "x"},
        {"kind_change": ("manual", "cucumber")},
        {"kind_change": ("manual", "cucumber"), "definition": STEPS},
        {"kind_change": ("manual", "manual"), "definition": STEPS},
        {"kind_change": ("other", "manual"), "definition": STEPS},
        {"scenario_type_change": ("scenario", "scenario_outline")},
        {
            "scenario_type_change": ("scenario", "scenario_outline"),
            "definition": CucumberDefinition("Given a", outline=False),
        },
        {"scenario_type_change": ("scenario", "scenario"), "definition": CucumberDefinition("x")},
        {
            "kind_change": ("manual", "cucumber"),
            "scenario_type_change": ("scenario", "scenario_outline"),
            "definition": CucumberDefinition("x", outline=True),
        },
    ],
    ids=[
        "empty",
        "no-key",
        "no-issue-id",
        "kind-without-definition",
        "kind-with-wrong-definition",
        "kind-unchanged",
        "kind-from-other",
        "outline-without-definition",
        "outline-mismatch",
        "outline-unchanged",
        "kind-and-outline",
    ],
)
def test_invalid_patches_are_rejected(values: dict[str, object]) -> None:
    arguments = {"key": "QA-1", "issue_id": "10001", **values}

    with pytest.raises(ValueError):
        XrayTestPatch(**arguments)  # type: ignore[arg-type]


def test_changed_names_only_the_members_that_are_set() -> None:
    patch = XrayTestPatch(
        key="QA-1",
        issue_id="10001",
        summary="New",
        kind_change=("cucumber", "manual"),
        definition=STEPS,
        add_component="Web",
        add_story_link=IssueLinkRef("Test", "outward", "ABC-1"),
    )

    assert patch.changed == ("summary", "test_type", "steps", "component", "story_link")
    assert XrayTestPatch(key="QA-1", issue_id="1", add_component="Web").changed == ("component",)
