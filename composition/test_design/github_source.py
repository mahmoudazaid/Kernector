"""GitHub Issues as a Test Design source (the only GitHub-aware Test Design code)."""

from __future__ import annotations

from collections.abc import Callable

from application.errors import (
    GitHubNotConnectedError,
    GitHubReauthorizationRequiredError,
    InsufficientEvidenceError,
    SourceItemNotFoundError,
)
from composition.test_design.errors import TestDesignValidationError
from composition.test_design.sources import AmbiguousSourceLocatorError
from domain.errors import ConnectorAuthError, ConnectorNotFoundError
from domain.knowledge import SourceDocument, SourceLocator
from domain.ports import LiveSourceReader
from infrastructure.config import Settings
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
_NOT_FOUND = "The GitHub Issue was not found."
_NOT_CONNECTED = "GitHub is not connected"
_REAUTH_REQUIRED = "GitHub authorization was revoked"


class GitHubTestDesignSource:
    """``TestDesignSource`` over a single live GitHub Issue."""

    provider = "github"

    def __init__(self, *, open_reader: Callable[[], LiveSourceReader]) -> None:
        self._open_reader = open_reader

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
        return self._open_reader()


def build_github_test_design_source(
    settings: Settings,
    *,
    connection_store=None,
    oauth_gateway=None,
    client_factory=None,
) -> GitHubTestDesignSource:
    """Build the source over the stored GitHub grant or an anonymous public reader.

    Usable OAuth tokens (including grants without Hub sync selection) keep the
    authenticated retrying reader. Missing/blank tokens and pre-existing
    ``reauthorization_required`` use an unauthenticated public Issue read.
    Building the source never requires a connection or a network call.
    """
    from composition.github.connection import (
        AuthRetryingGitHubIssueReader,
        _github_connection_store,
    )
    from infrastructure.connectors.github.issue_source_reader import (
        GitHubIssueSourceReader,
    )

    def open_reader() -> LiveSourceReader:
        tokens_store = (
            connection_store
            if connection_store is not None
            else _github_connection_store(settings)
        )
        connection = tokens_store.load()
        if connection is not None and not connection.reauthorization_required:
            token = connection.access_token
            if isinstance(token, str) and token.strip():
                return _TranslatingIssueReader(
                    AuthRetryingGitHubIssueReader(
                        settings=settings,
                        access_token=token.strip(),
                        tokens_store=tokens_store,
                        connection=connection,
                        oauth_gateway=oauth_gateway,
                        client_factory=client_factory,
                    )
                )
        unreadable_as: type[Exception]
        unreadable_message: str
        if connection is not None and connection.reauthorization_required:
            unreadable_as = GitHubReauthorizationRequiredError
            unreadable_message = _REAUTH_REQUIRED
        else:
            unreadable_as = GitHubNotConnectedError
            unreadable_message = _NOT_CONNECTED
        return _TranslatingIssueReader(
            GitHubIssueSourceReader(
                _anonymous_github_client(settings, client_factory=client_factory)
            ),
            unreadable_as=unreadable_as,
            unreadable_message=unreadable_message,
        )

    return GitHubTestDesignSource(open_reader=open_reader)


def _anonymous_github_client(settings: Settings, *, client_factory):
    """Build an Issue client with no Authorization header (never a configured PAT)."""
    if client_factory is not None:
        return client_factory(None)
    try:
        from infrastructure.connectors.github.client import HttpGitHubClient
    except ImportError as error:
        from application.errors import ConfigurationError
        from composition.github.connection import GITHUB_CLIENT_MISSING_MESSAGE

        raise ConfigurationError(GITHUB_CLIENT_MISSING_MESSAGE) from error
    return HttpGitHubClient(None, page_size=settings.github.page_size)


class _TranslatingIssueReader:
    """Keep GitHub Issue reader errors inside the GitHub source boundary."""

    def __init__(
        self,
        inner: LiveSourceReader,
        *,
        unreadable_as: type[Exception] | None = None,
        unreadable_message: str | None = None,
    ) -> None:
        self._inner = inner
        self._unreadable_as = unreadable_as
        self._unreadable_message = unreadable_message

    def fetch(self, locator: SourceLocator) -> SourceDocument:
        try:
            return self._inner.fetch(locator)
        except GitHubIssueEmptyBodyError as error:
            raise InsufficientEvidenceError(_NO_EVIDENCE) from error
        except ConnectorNotFoundError as error:
            raise self._map_unreadable(error) from error
        except ConnectorAuthError as error:
            if self._unreadable_as is None:
                raise
            raise self._map_unreadable(error) from error
        except (GitHubIssueNotIssueError, GitHubIssueLocatorMismatchError) as error:
            raise TestDesignValidationError(_INVALID_REQUEST) from error

    def _map_unreadable(self, _error: Exception) -> Exception:
        if self._unreadable_as is None:
            return SourceItemNotFoundError(_NOT_FOUND)
        message = self._unreadable_message or _NOT_CONNECTED
        return self._unreadable_as(message)
