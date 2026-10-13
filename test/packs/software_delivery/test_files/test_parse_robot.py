"""Seam: ``parse_test_file`` on Robot Framework ``.robot`` content (#396)."""

from __future__ import annotations

from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.test_files.parser import parse_test_file

TAGS = TestFileTagConfig(
    test_marker="XRay", story_marker="Story", manual_tags=("manual", "scaffold")
)


def _robot(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_only_scenario_test_cases_become_specs_with_bdd_steps_and_arguments() -> None:
    text = _robot(
        "*** Test Cases ***",
        "Helper Case",
        "    Given something",
        "Scenario: User logs in",
        "    Log    not a step",
        "    Given the user opens    ${LOGIN URL}    with spaces kept",
        "    When the user submits    admin",
        "    GivenSomething    is not a step",
        "    Then the dashboard is shown",
    )

    parsed = parse_test_file("tests/login.robot", text, TAGS)

    assert parsed.format == "robot"
    [scenario] = parsed.scenarios
    assert (scenario.source_path, scenario.line, scenario.summary) == (
        "tests/login.robot",
        4,
        "User logs in",
    )
    assert [(s.line, s.keyword, s.arguments) for s in scenario.steps] == [
        (6, "Given", ("the user opens", "${LOGIN URL}", "with spaces kept")),
        (7, "When", ("the user submits", "admin")),
        (9, "Then", ("the dashboard is shown",)),
    ]
    assert scenario.steps[0].text == "Given the user opens    ${LOGIN URL}    with spaces kept"
    assert scenario.kind == "cucumber"


def test_pipe_and_tab_separated_cells_and_continuations_attach_to_the_step() -> None:
    text = _robot(
        "| *** Test Cases *** |",
        "| Scenario: Pipe syntax |",
        "|    | Given a user | admin |",
        "|    | ...          | secret | MFA on |",
        "Scenario: Tab syntax",
        "\tWhen the user types\tadmin",
        "\t...\tsecret",
        "    Log    noise",
        "    ...    belongs to Log",
        "    Then it works",
    )

    pipe, tab = parse_test_file("t.robot", text, TAGS).scenarios

    assert pipe.summary == "Pipe syntax"
    assert [s.arguments for s in pipe.steps] == [("a user", "admin", "secret", "MFA on")]
    assert tab.summary == "Tab syntax"
    assert [(s.line, s.arguments) for s in tab.steps] == [
        (6, ("the user types", "admin", "secret")),
        (10, ("it works",)),
    ]


def test_mixed_whitespace_runs_are_one_separator_and_tight_pipes_keep_empty_cells() -> None:
    text = _robot(
        "*** Test Cases ***",
        "Scenario: Mixed whitespace",
        "    [Tags]  \tsmoke    XRay ABC-1",
        "    Given user opens  \tadmin",
        "| Scenario: Tight pipes |",
        "| | Given user opens | | admin |",
    )

    mixed, tight = parse_test_file("t.robot", text, TAGS).scenarios

    assert mixed.tags.local.plain == ("smoke",)
    assert mixed.xray_key == "ABC-1"
    [step] = mixed.steps
    assert (step.arguments, step.text) == (("user opens", "admin"), "Given user opens    admin")
    assert [s.arguments for s in tight.steps] == [("user opens", "", "admin")]


def test_a_leading_bom_is_ignored() -> None:
    text = "\ufeff" + _robot(
        "*** Settings ***",
        "Default Tags    Story ABC-9    manual",
        "*** Test Cases ***",
        "Scenario: A",
        "    Given something",
    )

    parsed = parse_test_file("t.robot", text, TAGS)

    [scenario] = parsed.scenarios
    assert (parsed.story_key, scenario.kind) == ("ABC-9", "manual")


def test_tags_lines_merge_with_continuations_and_manual_tags_set_the_kind() -> None:
    text = _robot(
        "*** Test Cases ***",
        "Scenario: Manual check",
        "    [Tags]    smoke    regression",
        "    ...    Scaffold",
        "    [Documentation]    not a tag",
        "    ...    still documentation",
        "    [Tags]    smoke    ui",
        "    Given something",
        "Scenario: Automated",
        "    [Tags]    smoke",
        "    Given something",
    )

    manual, automated = parse_test_file("t.robot", text, TAGS).scenarios

    assert manual.tags.local.plain == ("smoke", "regression", "Scaffold", "ui")
    assert manual.tags.effective_plain == ("smoke", "regression", "Scaffold", "ui")
    assert manual.kind == "manual"
    assert automated.kind == "cucumber"


def test_default_tags_story_survives_scenario_tags_but_plain_defaults_do_not() -> None:
    text = _robot(
        "*** Settings ***",
        "Default Tags    ABC-123    manual",
        "Test Tags    team-a",
        "",
        "*** Test Cases ***",
        "Scenario: Own tags",
        "    [Tags]    smoke",
        "    Given something",
        "Scenario: No tags",
        "    Given something",
        "Scenario: Own story",
        "    [Tags]    Story ABC-9",
        "    Given something",
    )

    parsed = parse_test_file("t.robot", text, TAGS)
    own, inherited, override = parsed.scenarios

    assert parsed.story_key == "ABC-123"
    assert parsed.file_tags.candidate_keys == ("ABC-123",)
    assert own.story_key == "ABC-123"
    assert own.tags.inherited.plain == ("team-a",)
    assert own.tags.effective_plain == ("team-a", "smoke")
    assert own.kind == "cucumber"
    assert inherited.tags.effective_plain == ("manual", "team-a")
    assert inherited.kind == "manual"
    assert (override.story_key, override.tags.local.story_key) == ("ABC-9", "ABC-9")
    assert override.tags.inherited.candidate_keys == ("ABC-123",)
