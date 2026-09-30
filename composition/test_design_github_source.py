"""GitHub Issues as a Test Design source (the only GitHub-aware Test Design code)."""

from __future__ import annotations

from collections.abc import Callable

from application.errors import GitHubNotConnectedError, InsufficientEvidenceError
from composition.test_design_errors import TestDesignValidationError
from composition.test_design_sources import AmbiguousSourceLocatorError
from domain.knowledge import SourceDocument, SourceLocator
from domain.ports import LiveSourceReader
from infrastructure.connectors.github.issue_locator import (
    AmbiguousGitHubIssueLocatorError,
    InvalidGitHubIssueLocatorError,
    canonicalize_github_issue_locator,
    extract_github_issue_locator,
)
from infrastructure.connectors.github.issue_source_reader import (
    GitHubIssueEmptyBodyError,
    GitHubIssueLocatorMismatchError,
    GitHubIssueNotIssueError,
)

_INVALID_REQUEST = "The test-design request was invalid."
_NO_EVIDENCE = "No usable grounded evidence for test coverage planning."


class GitHubTestDesignSource:
    """``TestDesignSource`` over a single live GitHub Issue."""

    provider = "github"

    def __init__(
        self,
        *,
        preflight: Callable[[], str],
        reader_factory: Callable[[str], LiveSourceReader],
    ) -> None:
        self._preflight = preflight
        self._reader_factory = reader_factory

    def canonicalize(self, locator: str) -> str:
        try:
            return canonicalize_github_issue_locator(locator)
        except InvalidGitHubIssueLocatorError as error:
            raise TestDesignValidationError(
                "source_locator.locator must be a GitHub Issue URL or owner/repo#number"
            ) from error

    def extract_locator(self, text: str) -> str | None:
        try:
            parsed = extract_github_issue_locator(text)
        except AmbiguousGitHubIssueLocatorError as error:
            raise AmbiguousSourceLocatorError(str(error)) from error
        return None if parsed is None else parsed.canonical

    def reader(self) -> LiveSourceReader:
        access_token = self._preflight()
        if not isinstance(access_token, str) or not access_token.strip():
            raise GitHubNotConnectedError("GitHub is not connected")
        return _TranslatingIssueReader(self._reader_factory(access_token.strip()))


class _TranslatingIssueReader:
    """Keep GitHub Issue reader errors inside the GitHub source boundary."""

    def __init__(self, inner: LiveSourceReader) -> None:
        self._inner = inner

    def fetch(self, locator: SourceLocator) -> SourceDocument:
        try:
            return self._inner.fetch(locator)
        except GitHubIssueEmptyBodyError as error:
            raise InsufficientEvidenceError(_NO_EVIDENCE) from error
        except (GitHubIssueNotIssueError, GitHubIssueLocatorMismatchError) as error:
            raise TestDesignValidationError(_INVALID_REQUEST) from error
