"""Tests for Software Delivery Gherkin phase parsing."""

import pytest

from packs.software_delivery.gherkin import parse_gherkin_steps


def test_valid_given_when_then_derives_expected_from_then_body() -> None:
    steps, expected = parse_gherkin_steps(
        [
            "Given the user is on login",
            "When credentials are submitted",
            "Then the home page is shown",
        ]
    )
    assert expected == "the home page is shown"
    assert steps[2] == "Then the home page is shown"


def test_multiple_then_phase_assertions_join_expected() -> None:
    _, expected = parse_gherkin_steps(
        [
            "Given account exists",
            "When user logs in",
            "Then session is created",
            "And dashboard is visible",
            "But no error banner is shown",
        ]
    )
    assert expected == (
        "session is created\ndashboard is visible\nno error banner is shown"
    )


def test_multiple_explicit_then_steps_preserved_in_expected() -> None:
    _, expected = parse_gherkin_steps(
        [
            "Given ready",
            "When action",
            "Then first",
            "Then second",
        ]
    )
    assert expected == "first\nsecond"


def test_blank_then_body_fails() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        parse_gherkin_steps(
            ["Given a", "When b", "Then "]
        )


def test_missing_then_fails() -> None:
    with pytest.raises(ValueError, match="missing"):
        parse_gherkin_steps(["Given a", "When b"])


def test_leading_and_fails() -> None:
    with pytest.raises(ValueError, match="orphan|leading"):
        parse_gherkin_steps(
            ["And something", "Given a", "When b", "Then c"]
        )


def test_phase_regression_then_to_when_fails() -> None:
    with pytest.raises(ValueError, match="regression"):
        parse_gherkin_steps(
            ["Given a", "When b", "Then c", "When again"]
        )


def test_given_to_then_skips_when_fails() -> None:
    with pytest.raises(ValueError, match="missing"):
        parse_gherkin_steps(["Given a", "Then c"])
