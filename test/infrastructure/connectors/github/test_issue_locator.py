"""Tests for authoritative GitHub issue locator parsing."""

from __future__ import annotations

import pytest

from infrastructure.connectors.github.issue_locator import (
    AmbiguousGitHubIssueLocatorError,
    InvalidGitHubIssueLocatorError,
    canonicalize_github_issue_locator,
    extract_github_issue_locator,
    parse_github_issue_locator,
)


def test_parses_full_github_issue_url() -> None:
    parsed = parse_github_issue_locator(
        "https://github.com/mahmoudazaid/Kernector/issues/293"
    )
    assert parsed is not None
    assert parsed.owner == "mahmoudazaid"
    assert parsed.repo == "Kernector"
    assert parsed.number == 293
    assert parsed.canonical == "mahmoudazaid/Kernector#293"


def test_parses_owner_repo_hash_number() -> None:
    parsed = parse_github_issue_locator("mahmoudazaid/Kernector#293")
    assert parsed is not None
    assert parsed.canonical == "mahmoudazaid/Kernector#293"


def test_extracts_locator_from_surrounding_prose() -> None:
    parsed = extract_github_issue_locator(
        "Design tests for https://github.com/mahmoudazaid/Kernector/issues/293 please"
    )
    assert parsed is not None
    assert parsed.canonical == "mahmoudazaid/Kernector#293"


def test_accepts_duplicate_mentions_of_same_issue() -> None:
    parsed = extract_github_issue_locator(
        "Design tests for mahmoudazaid/Kernector#293 "
        "and again https://github.com/mahmoudazaid/Kernector/issues/293"
    )
    assert parsed is not None
    assert parsed.canonical == "mahmoudazaid/Kernector#293"


def test_rejects_multiple_distinct_issues() -> None:
    with pytest.raises(AmbiguousGitHubIssueLocatorError):
        extract_github_issue_locator(
            "Design tests for mahmoudazaid/Kernector#293 and other/repo#1"
        )


def test_rejects_bare_number() -> None:
    assert parse_github_issue_locator("293") is None
    assert extract_github_issue_locator("Design tests for 293") is None


def test_rejects_malformed_locator() -> None:
    assert parse_github_issue_locator("not-a-locator") is None
    with pytest.raises(InvalidGitHubIssueLocatorError):
        canonicalize_github_issue_locator("not-a-locator")


def test_canonicalize_normalizes_url_to_owner_repo_hash() -> None:
    assert (
        canonicalize_github_issue_locator(
            "https://github.com/mahmoudazaid/Kernector/issues/293"
        )
        == "mahmoudazaid/Kernector#293"
    )
