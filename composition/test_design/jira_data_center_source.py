"""Jira Data Center issues as a Test Design source (the only Jira-aware Test Design code).

Every failure leaving the reader is a freshly built provider-neutral error with
no cause or context, so Jira diagnostics (response bodies, URLs) never reach
responses or logged tracebacks.
"""

from __future__ import annotations

from collections.abc import Callable

from application.errors import (
    InsufficientEvidenceError,
    JiraDataCenterCredentialsRejectedError,
    SourceItemNotFoundError,
    SourceNotConnectedError,
    SourceReauthorizationRequiredError,
)
from composition.jira.data_center import authenticated_call
from composition.test_design.errors import TestDesignValidationError
from composition.test_design.sources import AmbiguousSourceLocatorError
from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorNetworkError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    ConnectorUnavailableError,
)
from domain.knowledge import SourceDocument, SourceLocator
from domain.ports import LiveSourceReader
from infrastructure.config import JiraDataCenterSettings
from infrastructure.connectors.jira.data_center_state import JiraDataCenterStateStore
from infrastructure.connectors.jira.issue_locator import (
    AmbiguousJiraIssueLocatorError,
    InvalidJiraIssueLocatorError,
    JiraBrowseBase,
    canonicalize_jira_issue_locator,
    extract_jira_issue_locator,
)
from infrastructure.connectors.jira.issue_source_reader import (
    JiraDataCenterIssueClient,
    JiraDataCenterIssueSourceReader,
    JiraIssueEmptyEvidenceError,
    JiraIssuePayloadError,
)

_INVALID_LOCATOR = "source_locator.locator must be a Jira issue key or browse URL"
_INVALID_REQUEST = "The test-design request was invalid."
_NO_EVIDENCE = "No usable grounded evidence for test coverage planning."
_NOT_FOUND = "The source item was not found."
_NOT_CONNECTED = "The source is not connected."
_REJECTED = "The source authorization was rejected. Connect again."
_TRANSPORT_ERRORS: tuple[tuple[type[ConnectorError], str], ...] = (
    (ConnectorRateLimitError, "The source rate limit was exceeded."),
    (ConnectorTimeoutError, "The source request timed out."),
    (ConnectorNetworkError, "The source network request failed."),
    (ConnectorUnavailableError, "The source is temporarily unavailable."),
)
_REQUEST_FAILED = "The source request failed."


class JiraDataCenterTestDesignSource:
    """``TestDesignSource`` over a single live Jira Data Center issue.

    ``canonicalize`` is pure parsing over the configured base URL. Readiness
    (token present, token not rejected) is checked only by ``reader``.
    """

    provider = "jira"

    def __init__(
        self,
        *,
        settings_provider: Callable[[], JiraDataCenterSettings],
        state_store: JiraDataCenterStateStore,
        client_factory: Callable[[str, str], JiraDataCenterIssueClient],
    ) -> None:
        self._settings_provider = settings_provider
        self._state_store = state_store
        self._client_factory = client_factory
        base_url = settings_provider().base_url
        self._browse_base = JiraBrowseBase.parse(base_url) if base_url else None

    def canonicalize(self, locator: str) -> str:
        try:
            return canonicalize_jira_issue_locator(locator, base=self._browse_base)
        except InvalidJiraIssueLocatorError as error:
            raise TestDesignValidationError(_INVALID_LOCATOR) from error

    def extract_locator(self, text: str) -> str | None:
        state = self._state_store.load()
        try:
            return extract_jira_issue_locator(
                text,
                base=self._browse_base,
                project_keys=() if state is None else state.project_keys,
            )
        except AmbiguousJiraIssueLocatorError as error:
            raise AmbiguousSourceLocatorError(str(error)) from error

    def reader(self) -> LiveSourceReader:
        settings = self._settings_provider()
        if not settings.configured:
            raise SourceNotConnectedError(_NOT_CONNECTED)
        state = self._state_store.load()
        if state is not None and state.credentials_rejected:
            raise SourceReauthorizationRequiredError(_REJECTED)
        assert settings.base_url is not None and settings.token is not None
        client = self._client_factory(settings.base_url, settings.token)
        return _NeutralIssueReader(
            JiraDataCenterIssueSourceReader(
                client,
                acceptance_criteria_field=settings.acceptance_criteria_field,
            ),
            self._state_store,
        )


def build_jira_data_center_test_design_source(
    settings_provider: Callable[[], JiraDataCenterSettings],
    *,
    state_store: JiraDataCenterStateStore | None = None,
    client_factory: Callable[[str, str], JiraDataCenterIssueClient] | None = None,
) -> JiraDataCenterTestDesignSource:
    """Build the source over the connector state file and the HTTP client."""

    def http_client(base_url: str, token: str) -> JiraDataCenterIssueClient:
        from infrastructure.connectors.jira.data_center import HttpJiraDataCenterClient

        return HttpJiraDataCenterClient(base_url, token)

    return JiraDataCenterTestDesignSource(
        settings_provider=settings_provider,
        state_store=(
            state_store
            if state_store is not None
            else JiraDataCenterStateStore(settings_provider().state_path)
        ),
        client_factory=client_factory if client_factory is not None else http_client,
    )


class _NeutralIssueReader:
    """Record token rejection and translate every Jira failure to a neutral error."""

    def __init__(
        self, inner: LiveSourceReader, state_store: JiraDataCenterStateStore
    ) -> None:
        self._inner = inner
        self._state_store = state_store

    def fetch(self, locator: SourceLocator) -> SourceDocument:
        try:
            return authenticated_call(
                self._state_store, lambda: self._inner.fetch(locator)
            )
        except JiraDataCenterCredentialsRejectedError:
            failure: Exception = SourceReauthorizationRequiredError(_REJECTED)
        except JiraIssueEmptyEvidenceError:
            failure = InsufficientEvidenceError(_NO_EVIDENCE)
        except JiraIssuePayloadError:
            failure = TestDesignValidationError(_INVALID_REQUEST)
        except ConnectorNotFoundError:
            failure = SourceItemNotFoundError(_NOT_FOUND)
        except ConnectorError as error:
            failure = _neutral_connector_error(error)
        # Raised outside the handler so the Jira error is not kept as __context__.
        raise failure from None


def _neutral_connector_error(error: ConnectorError) -> Exception:
    if isinstance(error, ConnectorAuthError):
        return SourceReauthorizationRequiredError(_REJECTED)
    for error_type, message in _TRANSPORT_ERRORS:
        if isinstance(error, error_type):
            return error_type(message)
    return ConnectorError(_REQUEST_FAILED)
