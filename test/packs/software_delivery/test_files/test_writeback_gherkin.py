"""Seam: ``rewrite_file`` on Gherkin ``.feature`` content (#399)."""

from __future__ import annotations

import pytest

from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.test_files.writeback import FileRewrite, rewrite_file

TAGS = TestFileTagConfig(test_marker="XRay", story_marker="Story", manual_tags=("manual",))
PATH = "features/login.feature"


def _feature(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _rewrite(text: str, keys: dict[str, str]) -> FileRewrite:
    result = rewrite_file(PATH, text, keys, TAGS)
    again = rewrite_file(PATH, result.content, keys, TAGS)
    assert again.content == result.content
    assert not again.changed
    assert {s.status for s in again.scenarios} == {"UNCHANGED"}
    return result


def test_untagged_scenario_gets_the_tag_line_directly_above_its_header() -> None:
    text = _feature("Feature: Login", "", "  Scenario: Valid login", "    Given a user")

    result = _rewrite(text, {"Valid login": "ABC-9"})

    assert result.content == _feature(
        "Feature: Login", "", "  @XRay:ABC-9", "  Scenario: Valid login", "    Given a user"
    )
    assert result.changed
    [scenario] = result.scenarios
    assert (scenario.line, scenario.summary, scenario.key) == (3, "Valid login", "ABC-9")
    assert (scenario.previous_key, scenario.status) == (None, "TAGGED")


def test_tag_is_appended_to_the_line_nearest_the_header_and_feature_tags_stay() -> None:
    text = _feature(
        "@Story:ABC-1 @XRay-like",
        "Feature: Login",
        "  @smoke",
        "  @team-a",
        "  Scenario: Valid login",
        "    Given a user",
    )

    result = _rewrite(text, {"Valid login": "ABC-9"})

    assert result.content == _feature(
        "@Story:ABC-1 @XRay-like",
        "Feature: Login",
        "  @smoke",
        "  @team-a @XRay:ABC-9",
        "  Scenario: Valid login",
        "    Given a user",
    )


@pytest.mark.parametrize("old", ["XRay:ABC-2", "xray=ABC-2", "ABC-2:XRay", "ABC-2=XRAY"])
def test_every_marker_form_is_replaced_in_place(old: str) -> None:
    text = _feature(
        "Feature: Login", f"  @smoke @{old} @fast", "  Scenario: Valid login", "    Given x"
    )

    result = _rewrite(text, {"Valid login": "ABC-9"})

    assert result.content == _feature(
        "Feature: Login", "  @smoke @XRay:ABC-9 @fast", "  Scenario: Valid login", "    Given x"
    )
    [scenario] = result.scenarios
    assert (scenario.previous_key, scenario.status) == ("ABC-2", "REPLACED")


def test_outline_and_example_headers_are_found_and_examples_tags_stay() -> None:
    text = _feature(
        "Feature: Login",
        "  Example: One",
        "    Given x",
        "",
        "  Scenario Outline: Two <a>",
        "    Given <a>",
        "    @XRay-ish @fast",
        "    Examples: Data",
        "      | a |",
        "      | 1 |",
    )

    result = _rewrite(text, {"One": "ABC-8", "Two <a>": "ABC-9"})

    assert result.content == _feature(
        "Feature: Login",
        "  @XRay:ABC-8",
        "  Example: One",
        "    Given x",
        "",
        "  @XRay:ABC-9",
        "  Scenario Outline: Two <a>",
        "    Given <a>",
        "    @XRay-ish @fast",
        "    Examples: Data",
        "      | a |",
        "      | 1 |",
    )


def test_comment_lines_stay_and_a_commented_tag_line_is_never_edited() -> None:
    text = _feature(
        "Feature: Login",
        "  @smoke # owned by team a",
        "  # a standalone comment",
        "  Scenario: Valid login",
        "    Given x",
    )

    result = _rewrite(text, {"Valid login": "ABC-9"})

    assert result.content == _feature(
        "Feature: Login",
        "  @smoke # owned by team a",
        "  # a standalone comment",
        "  @XRay:ABC-9",
        "  Scenario: Valid login",
        "    Given x",
    )


def test_old_marker_on_a_commented_tag_line_is_rejected() -> None:
    text = _feature(
        "Feature: Login", "  @XRay:ABC-2 # old", "  Scenario: Valid login", "    Given x"
    )

    with pytest.raises(TestFileValidationError) as caught:
        rewrite_file(PATH, text, {"Valid login": "ABC-9"}, TAGS)

    assert (caught.value.path, caught.value.line) == (PATH, 2)
    assert caught.value.reason is Reason.COMMENTED_TAG_LINE


def test_only_markers_and_the_assigned_key_are_deduplicated() -> None:
    text = _feature(
        "Feature: Login",
        "  @a @a @ABC-9 @ABC-3 @Story:ABC-4",
        "  Scenario: Valid login",
        "    Given x",
    )

    result = _rewrite(text, {"Valid login": "ABC-9"})

    assert result.content == _feature(
        "Feature: Login",
        "  @a @a @XRay:ABC-9 @ABC-3 @Story:ABC-4",
        "  Scenario: Valid login",
        "    Given x",
    )
    [scenario] = result.scenarios
    assert (scenario.previous_key, scenario.status) == (None, "TAGGED")


def test_duplicate_markers_with_the_same_key_normalize_and_empty_lines_go() -> None:
    text = _feature(
        "Feature: Login",
        "  @xray=ABC-9 @smoke",
        "  @XRay:ABC-9 @ABC-9",
        "  Scenario: Valid login",
        "    Given x",
    )

    result = _rewrite(text, {"Valid login": "ABC-9"})

    assert result.content == _feature(
        "Feature: Login", "  @XRay:ABC-9 @smoke", "  Scenario: Valid login", "    Given x"
    )
    [scenario] = result.scenarios
    assert (scenario.previous_key, scenario.status) == ("ABC-9", "NORMALIZED")


def test_canonical_tag_is_unchanged_and_yields_no_diff() -> None:
    text = _feature("Feature: Login", "  @XRay:ABC-9", "  Scenario: Valid login", "    Given x")

    result = rewrite_file(PATH, text, {"Valid login": "ABC-9"}, TAGS)

    assert (result.content, result.changed, result.diff) == (text, False, "")
    assert result.scenarios[0].status == "UNCHANGED"
