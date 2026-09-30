"""Tests for the GitHub Test Design source adapter (#351)."""

from __future__ import annotations

import pytest

from application.errors import (
    GitHubNotConnectedError,
    InsufficientEvidenceError,
    SourceNotConnectedError,
)
from composition.test_design_errors import TestDesignValidationError
from composition.test_design_github_source import GitHubTestDesignSource
from composition.test_design_sources import AmbiguousSourceLocatorError
from domain.knowledge import SourceLocator
from infrastructure.connectors.github.issue_source_reader import (
    GitHubIssueEmptyBodyError,
    GitHubIssueLocatorMismatchError,
    GitHubIssueNotIssueError,
)
from test.composition.test_design_fakes import RecordingIssueReader, issue_document


def _source(
    *,
    token: str = "token",
    reader: RecordingIssueReader | None = None,
    tokens_seen: list[str] | None = None,
) -> GitHubTestDesignSource:
    active = reader or RecordingIssueReader()

    def reader_factory(access_token: str) -> RecordingIssueReader:
        if tokens_seen is not None:
            tokens_seen.append(access_token)
        return active

    return GitHubTestDesignSource(
        preflight=lambda: token,
        reader_factory=reader_factory,  # type: ignore[arg-type]
    )


def test_provider_is_github() -> None:
    assert _source().provider == "github"


@pytest.mark.parametrize(
    "locator",
    [
        "https://github.com/acme/app/issues/7",
        " acme/app#7 ",
    ],
)
def test_canonicalize_accepts_issue_url_and_hash_form(locator: str) -> None:
    assert _source().canonicalize(locator) == "acme/app#7"


@pytest.mark.parametrize("locator", ["", "7", "https://github.com/acme/app/pull/7"])
def test_canonicalize_rejects_non_issue_locators(locator: str) -> None:
    with pytest.raises(TestDesignValidationError):
        _source().canonicalize(locator)


def test_extract_locator_finds_one_issue_or_none() -> None:
    source = _source()

    assert source.extract_locator("Design tests for acme/app#7") == "acme/app#7"
    assert source.extract_locator("Design tests for 7") is None


def test_extract_locator_rejects_multiple_distinct_issues() -> None:
    with pytest.raises(AmbiguousSourceLocatorError, match="exactly one"):
        _source().extract_locator("Compare acme/web#10 and acme/api#11")


@pytest.mark.parametrize("token", ["", "   "])
def test_reader_without_token_is_not_connected_and_never_builds_a_reader(
    token: str,
) -> None:
    seen: list[str] = []

    with pytest.raises(SourceNotConnectedError) as raised:
        _source(token=token, tokens_seen=seen).reader()

    assert isinstance(raised.value, GitHubNotConnectedError)
    assert seen == []


def test_reader_fetches_with_the_stripped_token() -> None:
    reader = RecordingIssueReader(issue_document())
    seen: list[str] = []
    locator = SourceLocator(provider="github", locator="acme/app#7")

    document = _source(token=" tok ", reader=reader, tokens_seen=seen).reader().fetch(
        locator
    )

    assert seen == ["tok"]
    assert reader.calls == [locator]
    assert document == reader.document


def test_reader_maps_empty_issue_body_to_insufficient_evidence() -> None:
    reader = RecordingIssueReader()
    reader.error = GitHubIssueEmptyBodyError("raw empty detail")

    with pytest.raises(InsufficientEvidenceError):
        _source(reader=reader).reader().fetch(
            SourceLocator(provider="github", locator="acme/app#7")
        )


@pytest.mark.parametrize(
    "error",
    [
        GitHubIssueNotIssueError("raw pull request detail"),
        GitHubIssueLocatorMismatchError("raw mismatch detail"),
    ],
)
def test_reader_maps_non_issue_and_mismatch_to_sanitized_validation(
    error: Exception,
) -> None:
    reader = RecordingIssueReader()
    reader.error = error

    with pytest.raises(TestDesignValidationError) as raised:
        _source(reader=reader).reader().fetch(
            SourceLocator(provider="github", locator="acme/app#7")
        )

    assert str(raised.value) == "The test-design request was invalid."
