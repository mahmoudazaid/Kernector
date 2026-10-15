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


def test_robot_summary_with_separator_run_is_unsupported() -> None:
    steps = (XrayTestStep(action="Go"),)
    for summary in ("Login  twice", "Login\ttwice"):
        details = _details(steps=steps, summary=summary)

        robot = render_scenario(details, "robot", TAGS)
        feature = render_scenario(details, "feature", TAGS)

        assert isinstance(robot, RenderUnsupported)
        assert robot.reason == "robot_summary_separator"
        assert isinstance(feature, ScenarioRender)


def test_explicit_scenario_type_overrides_outline_heuristic() -> None:
    gherkin = "Given the cart total is > 10\nThen the discount is < 5"
    details = _details(kind="cucumber", gherkin=gherkin, scenario_type="scenario")

    robot = render_scenario(details, "robot", TAGS)
    feature = render_scenario(details, "feature", TAGS)

    assert isinstance(robot, ScenarioRender)
    assert isinstance(feature, ScenarioRender)
    assert "Scenario: User logs in" in feature.text
    assert "Scenario Outline" not in feature.text


def test_outline_heuristic_needs_examples_line_when_type_unknown() -> None:
    angle = _details(kind="cucumber", gherkin="Given a < b > c")
    examples = _details(
        kind="cucumber", gherkin="Given user <name>\nExamples:\n  | name |\n  | ann |"
    )

    plain = render_scenario(angle, "feature", TAGS)
    outline = render_scenario(examples, "feature", TAGS)

    assert isinstance(plain, ScenarioRender) and "Scenario Outline" not in plain.text
    assert isinstance(outline, ScenarioRender) and "Scenario Outline:" in outline.text


def test_robot_manual_data_is_a_continuation_row() -> None:
    details = _details(
        steps=(XrayTestStep(action="Enter credentials", data="user=bob", expected="Logged in"),)
    )

    rendered = render_scenario(details, "robot", TAGS)

    assert isinstance(rendered, ScenarioRender)
    assert "    Given Enter credentials\n    ...    user=bob\n    Then Logged in" in rendered.text


def test_blank_lines_in_manual_step_are_skipped() -> None:
    details = _details(steps=(XrayTestStep(action="Open\n\nGo", expected="A\n\nB"),))

    robot = render_scenario(details, "robot", TAGS)
    feature = render_scenario(details, "feature", TAGS)

    assert isinstance(robot, ScenarioRender) and isinstance(feature, ScenarioRender)
    for rendered in (robot, feature):
        steps = [line.strip() for line in rendered.text.splitlines()[2:]]
        assert steps == ["Given Open", "And Go", "Then A", "And B"]


def test_manual_with_steps_is_not_tagged_scaffold() -> None:
    details = _details(steps=(XrayTestStep(action="Go"),))

    robot = render_scenario(details, "robot", TAGS)
    feature = render_scenario(details, "feature", TAGS)

    assert isinstance(robot, ScenarioRender) and isinstance(feature, ScenarioRender)
    assert "[Tags]    XRay:QA-7    manual\n" in robot.text
    assert "@XRay:QA-7 @manual\n" in feature.text
    assert "scaffold" not in robot.text + feature.text


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
