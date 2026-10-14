"""Seam: ``render_scenario`` / ``new_file_text`` (#400)."""

from __future__ import annotations

from domain.test_management.xray import XrayTestDetails, XrayTestStep
from packs.software_delivery.test_files.from_xray import (
    RenderUnsupported,
    ScenarioRender,
    new_file_text,
    render_scenario,
)
from packs.software_delivery.test_files.models import TestFileTagConfig

TAGS = TestFileTagConfig("XRay", "Story", ("manual", "scaffold"))


def _details(
    *,
    kind: str = "manual",
    steps: tuple[XrayTestStep, ...] = (),
    gherkin: str = "",
    scenario_type: str | None = None,
    preconditions: int = 0,
    summary: str = "User logs in",
) -> XrayTestDetails:
    return XrayTestDetails(
        key="QA-7",
        issue_id="10007",
        summary=summary,
        kind=kind,  # type: ignore[arg-type]
        scenario_type=scenario_type,  # type: ignore[arg-type]
        steps=steps,
        gherkin=gherkin,
        preconditions=preconditions,
    )


def test_manual_action_and_expected_become_given_then() -> None:
    details = _details(
        steps=(XrayTestStep(action="Open login", expected="Form shown"),)
    )

    rendered = render_scenario(details, "robot", TAGS)

    assert isinstance(rendered, ScenarioRender)
    assert "Given Open login" in rendered.text
    assert "Then Form shown" in rendered.text
    assert "XRay:QA-7" in rendered.text
    assert "manual" in rendered.text


def test_blank_action_with_expected_is_unsupported() -> None:
    details = _details(steps=(XrayTestStep(action="", expected="ok"),))

    result = render_scenario(details, "feature", TAGS)

    assert isinstance(result, RenderUnsupported)
    assert result.reason == "empty_action_step"


def test_empty_steps_get_scaffold_and_todo() -> None:
    rendered = render_scenario(_details(steps=()), "robot", TAGS)

    assert isinstance(rendered, ScenarioRender)
    assert "scaffold" in rendered.text
    assert "TODO" in rendered.text


def test_cucumber_outline_unsupported_on_robot() -> None:
    details = _details(
        kind="cucumber",
        gherkin="Given user <name>\n\nExamples:\n  | name |\n  | ann |",
        scenario_type="scenario_outline",
    )

    result = render_scenario(details, "robot", TAGS)

    assert isinstance(result, RenderUnsupported)
    assert result.reason == "robot_outline_unsupported"


def test_cucumber_outline_preserved_on_feature() -> None:
    gherkin = "Given user <name>\n\nExamples:\n  | name |\n  | ann |"
    details = _details(kind="cucumber", gherkin=gherkin, scenario_type="scenario_outline")

    rendered = render_scenario(details, "feature", TAGS)

    assert isinstance(rendered, ScenarioRender)
    assert "Scenario Outline:" in rendered.text
    assert "Examples:" in rendered.text
    assert "| ann |" in rendered.text


def test_preconditions_count_adds_warning_only() -> None:
    rendered = render_scenario(
        _details(steps=(XrayTestStep(action="Go"),), preconditions=2),
        "robot",
        TAGS,
    )

    assert isinstance(rendered, ScenarioRender)
    assert rendered.warnings == ("preconditions_present",)


def test_other_kind_is_unsupported() -> None:
    result = render_scenario(_details(kind="other"), "robot", TAGS)

    assert isinstance(result, RenderUnsupported)
    assert result.reason == "other_kind"


def test_new_file_headers_for_robot_and_feature() -> None:
    scenario = render_scenario(
        _details(steps=(XrayTestStep(action="Go"),)), "robot", TAGS
    )
    assert isinstance(scenario, ScenarioRender)

    robot = new_file_text(
        fmt="robot",
        story_key="ABC-1",
        story_summary="Login",
        scenarios=(scenario,),
        tags=TAGS,
    )
    assert robot.startswith("*** Settings ***\nDefault Tags    Story    ABC-1\n")
    assert "*** Test Cases ***" in robot

    feature_scenario = render_scenario(
        _details(steps=(XrayTestStep(action="Go"),)), "feature", TAGS
    )
    assert isinstance(feature_scenario, ScenarioRender)
    feature = new_file_text(
        fmt="feature",
        story_key="ABC-1",
        story_summary="Login story",
        scenarios=(feature_scenario,),
        tags=TAGS,
    )
    assert feature.startswith("@Story:ABC-1\nFeature: [ABC-1] Login story\n")
