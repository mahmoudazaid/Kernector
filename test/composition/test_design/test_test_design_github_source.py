"""Tests for the GitHub Test Design source adapter (#351, #302)."""

from __future__ import annotations

import pytest

from application.errors import (
    GitHubNotConnectedError,
    InsufficientEvidenceError,
)
from composition.test_design.errors import TestDesignValidationError
from composition.test_design.github_source import (
    GitHubTestDesignSource,
    _TranslatingIssueReader,
)
from composition.test_design.sources import AmbiguousSourceLocatorError
from domain.knowledge import SourceLocator
from infrastructure.connectors.github.issue_source_reader import (
    GitHubIssueEmptyBodyError,
    GitHubIssueLocatorMismatchError,
    GitHubIssueNotIssueError,
)
from test.composition.test_design.test_design_fakes import RecordingIssueReader, issue_document


def _source(*, reader: RecordingIssueReader | None = None) -> GitHubTestDesignSource:
    active = reader or RecordingIssueReader()
    return GitHubTestDesignSource(
        open_reader=lambda: _TranslatingIssueReader(active),
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


def test_reader_fetches_through_open_reader() -> None:
    reader = RecordingIssueReader(issue_document())
    locator = SourceLocator(provider="github", locator="acme/app#7")

    document = _source(reader=reader).reader().fetch(locator)

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


def test_anonymous_unreadable_maps_to_not_connected() -> None:
    from domain.errors import ConnectorNotFoundError

    reader = RecordingIssueReader()
    reader.error = ConnectorNotFoundError("missing")
    source = GitHubTestDesignSource(
        open_reader=lambda: _TranslatingIssueReader(
            reader,
            unreadable_as=GitHubNotConnectedError,
            unreadable_message="GitHub is not connected",
        )
    )

    with pytest.raises(GitHubNotConnectedError):
        source.reader().fetch(SourceLocator(provider="github", locator="acme/app#7"))
