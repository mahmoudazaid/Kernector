"""Seam: ``rewrite_file`` on Robot Framework ``.robot`` content (#399)."""

from __future__ import annotations

import pytest

from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.test_files.writeback import FileRewrite, rewrite_file

TAGS = TestFileTagConfig(test_marker="XRay", story_marker="Story", manual_tags=("manual",))
PATH = "tests/login.robot"


def _robot(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _rewrite(text: str, keys: dict[str, str]) -> FileRewrite:
    result = rewrite_file(PATH, text, keys, TAGS)
    again = rewrite_file(PATH, result.content, keys, TAGS)
    assert again.content == result.content
    assert {s.status for s in again.scenarios} == {"UNCHANGED"}
    return result


def test_tags_row_is_inserted_right_after_the_parsed_header() -> None:
    text = _robot("*** Test Cases ***", "Scenario: Login", "  Given a user")

    result = _rewrite(text, {"Login": "ABC-9"})

    assert result.content == _robot(
        "*** Test Cases ***", "Scenario: Login", "  [Tags]    XRay ABC-9", "  Given a user"
    )
    [scenario] = result.scenarios
    assert (scenario.line, scenario.previous_key, scenario.status) == (2, None, "TAGGED")


def test_header_with_an_inline_keyword_stays_byte_identical() -> None:
    text = _robot(
        "*** Test Cases ***",
        "Scenario: Login    Given inline    arg",
        "    When it runs",
        "Scenario: Only    Given inline",
    )

    result = _rewrite(text, {"Login": "ABC-8", "Only": "ABC-9"})

    assert result.content == _robot(
        "*** Test Cases ***",
        "Scenario: Login    Given inline    arg",
        "    [Tags]    XRay ABC-8",
        "    When it runs",
        "Scenario: Only    Given inline",
        "    [Tags]    XRay ABC-9",
    )


def test_tag_rows_merge_into_one_and_every_comment_is_kept_in_order() -> None:
    text = _robot(
        "*** Test Cases ***",
        "Scenario: Login",
        "  [Tags]    a    # first note",
        "    # standalone",
        "    ...    XRay ABC-2    b  # second note",
        "  [Tags]    c",
        "    Given x",
    )

    result = _rewrite(text, {"Login": "ABC-9"})

    assert result.content == _robot(
        "*** Test Cases ***",
        "Scenario: Login",
        "  [Tags]    a    XRay ABC-9    b    c    # first note",
        "    # standalone",
        "    # second note",
        "    Given x",
    )
    [scenario] = result.scenarios
    assert (scenario.previous_key, scenario.status) == ("ABC-2", "REPLACED")


@pytest.mark.parametrize(
    "old", ["XRay ABC-2", "xray:ABC-2", "XRay = ABC-2", "ABC-2 XRay", "ABC-2=xray"]
)
def test_every_marker_form_is_replaced_in_place(old: str) -> None:
    text = _robot(
        "*** Test Cases ***", "Scenario: Login", f"    [Tags]    {old}    smoke", "    Given x"
    )

    result = _rewrite(text, {"Login": "ABC-9"})

    assert result.content == _robot(
        "*** Test Cases ***", "Scenario: Login", "    [Tags]    XRay ABC-9    smoke", "    Given x"
    )


def test_only_markers_and_the_assigned_key_are_deduplicated() -> None:
    text = _robot(
        "*** Test Cases ***",
        "Scenario: Login",
        "    [Tags]    a    a    ABC-9    ABC-3    Story ABC-4    xray ABC-9",
        "    Given x",
    )

    result = _rewrite(text, {"Login": "ABC-9"})

    assert result.content == _robot(
        "*** Test Cases ***",
        "Scenario: Login",
        "    [Tags]    a    a    ABC-3    Story ABC-4    XRay ABC-9",
        "    Given x",
    )
    [scenario] = result.scenarios
    assert (scenario.previous_key, scenario.status) == ("ABC-9", "NORMALIZED")


def test_inserted_tags_copy_default_tags_including_continuations() -> None:
    text = _robot(
        "*** Settings ***",
        "Default Tags    smoke    manual",
        "...    Story ABC-1",
        "",
        "*** Test Cases ***",
        "Scenario: Login",
        "    Given x",
        "Scenario: Tagged",
        "    [Tags]    own",
        "    Given y",
    )

    result = _rewrite(text, {"Login": "ABC-8", "Tagged": "ABC-9"})

    assert result.content == _robot(
        "*** Settings ***",
        "Default Tags    smoke    manual",
        "...    Story ABC-1",
        "",
        "*** Test Cases ***",
        "Scenario: Login",
        "    [Tags]    smoke    manual    Story ABC-1    XRay ABC-8",
        "    Given x",
        "Scenario: Tagged",
        "    [Tags]    own    XRay ABC-9",
        "    Given y",
    )


def test_default_tags_copy_that_changes_the_story_choice_is_rejected() -> None:
    text = _robot(
        "*** Settings ***",
        "Default Tags    ABC-1    ABC-2",
        "*** Test Cases ***",
        "Scenario: Login",
        "    Given x",
    )

    with pytest.raises(TestFileValidationError) as caught:
        rewrite_file(PATH, text, {"Login": "ABC-9"}, TAGS)

    assert (caught.value.line, caught.value.reason) == (4, Reason.ROLE_CHANGE)


def test_pipe_separated_rows_are_rejected() -> None:
    text = _robot("| *** Test Cases *** |", "| Scenario: Pipe |", "|    | Given x |")

    with pytest.raises(TestFileValidationError) as caught:
        rewrite_file(PATH, text, {"Pipe": "ABC-9"}, TAGS)

    assert (caught.value.line, caught.value.reason) == (2, Reason.PIPE_ROWS_UNSUPPORTED)


def test_a_single_canonical_row_with_tabs_is_unchanged() -> None:
    text = _robot("*** Test Cases ***", "Scenario: Login", "\t[Tags]\tsmoke\tXRay ABC-9", "\tGiven x")

    result = rewrite_file(PATH, text, {"Login": "ABC-9"}, TAGS)

    assert (result.content, result.changed, result.scenarios[0].status) == (
        text,
        False,
        "UNCHANGED",
    )
