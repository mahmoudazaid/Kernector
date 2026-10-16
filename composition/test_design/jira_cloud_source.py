"""Jira Cloud issues as a Test Design source.

Cloud and Data Center are mutually exclusive: the composition root registers
this source only when Data Center mode is off and Jira Cloud OAuth is
configured. Failures leave as freshly built provider-neutral errors. The
neutral exception is built inside the handler and raised after it, so neither
``__cause__`` nor ``__context__`` keeps the Jira error.
"""

from __future__ import annotations

from collections.abc import Callable

from application.errors import (
    InsufficientEvidenceError,
    JiraNotConnectedError,
    JiraReauthorizationRequiredError,
    SourceItemNotFoundError,
    SourceNotConnectedError,
    SourceReauthorizationRequiredError,
)
from composition.errors import JiraConnectorError
from composition.jira.cloud import _with_access_token
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
from infrastructure.config import Settings
from infrastructure.connectors.jira.issue_locator import (
    AmbiguousJiraIssueLocatorError,
    InvalidJiraIssueLocatorError,
    JiraBrowseBase,
    canonicalize_jira_issue_locator,
    extract_jira_issue_locator,
)
from infrastructure.connectors.jira.issue_source_reader import (
    JiraCloudIssueClient,
    JiraCloudIssueSourceReader,
    JiraIssueEmptyEvidenceError,
    JiraIssuePayloadError,
)
from packs.software_delivery.test_design.suggest_tests import budget_evidence_text

_INVALID_LOCATOR = "source_locator.locator must be a Jira issue key or browse URL"
_INVALID_REQUEST = "The test-design request was invalid."
_NO_EVIDENCE = "No usable grounded evidence for test coverage planning."
_NOT_FOUND = "The source item was not found."
_NOT_CONNECTED = "The source is not connected."
_REJECTED = "The source authorization was rejected. Connect again."
_REQUEST_FAILED = "The source request failed."
_TRANSPORT_ERRORS: tuple[tuple[type[ConnectorError], str], ...] = (
    (ConnectorRateLimitError, "The source rate limit was exceeded."),
    (ConnectorTimeoutError, "The source request timed out."),
    (ConnectorNetworkError, "The source network request failed."),
    (ConnectorUnavailableError, "The source is temporarily unavailable."),
)


class JiraCloudTestDesignSource:
    """``TestDesignSource`` over one live Jira Cloud issue.

    ``canonicalize`` accepts any syntactically valid key and a browse URL on
    the saved site. It does not consult project selection. ``extract_locator``
    recognizes a bare key only when its project is selected, and a browse URL
    on the saved site even when that project is not. Both read the grant file
    on every call.

    Args:
        connection_store: Persisted Atlassian grant. Read on each call.
        gateway: OAuth gateway used by the existing refresh helper.
        client_factory: Builds a Cloud issue client from an access token and
            cloud id. Defaults to ``HttpJiraClient``.
        acceptance_criteria_field (str | None): Optional ``customfield_<digits>``.
    """

    provider = "jira"

    def __init__(
        self,
        *,
        connection_store,
        gateway,
        client_factory: Callable[[str, str], JiraCloudIssueClient] | None = None,
        acceptance_criteria_field: str | None = None,
    ) -> None:
        self._connection_store = connection_store
        self._gateway = gateway
        self._client_factory = client_factory
        self._acceptance_criteria_field = acceptance_criteria_field

    def canonicalize(self, locator: str) -> str:
        try:
            return canonicalize_jira_issue_locator(locator, base=self._browse_base())
        except InvalidJiraIssueLocatorError as error:
            raise TestDesignValidationError(_INVALID_LOCATOR) from error

    def extract_locator(self, text: str) -> str | None:
        connection = self._connection_store.load()
        projects = () if connection is None else connection.project_keys
        try:
            return extract_jira_issue_locator(
                text, base=self._browse_base(), project_keys=projects
            )
        except AmbiguousJiraIssueLocatorError as error:
            raise AmbiguousSourceLocatorError(str(error)) from error

    def reader(self) -> LiveSourceReader:
        self._require_connection()
        return _NeutralCloudReader(self)

    def _browse_base(self) -> JiraBrowseBase | None:
        connection = self._connection_store.load()
        if connection is None or connection.site is None:
            return None
        return JiraBrowseBase.parse(connection.site.site_url)

    def _require_connection(self):
        """Return the grant, or raise the readiness error with no network call.

        Precedence: missing grant, then reauthorization or a missing access
        token, then a grant that has not selected a site.
        """
        connection = self._connection_store.load()
        if connection is None:
            raise SourceNotConnectedError(_NOT_CONNECTED)
        if connection.reauthorization_required or not connection.access_token:
            raise SourceReauthorizationRequiredError(_REJECTED)
        if connection.site is None:
            raise SourceNotConnectedError(_NOT_CONNECTED)
        return connection

    def _client(self, access_token: str, cloud_id: str) -> JiraCloudIssueClient:
        if self._client_factory is not None:
            return self._client_factory(access_token, cloud_id)
        from infrastructure.connectors.jira.client import HttpJiraClient

        return HttpJiraClient(access_token, cloud_id)


def build_jira_cloud_test_design_source(
    settings: Settings,
    *,
    connection_store=None,
    gateway=None,
    client_factory: Callable[[str, str], JiraCloudIssueClient] | None = None,
) -> JiraCloudTestDesignSource:
    """Build the source over the Hub OAuth grant. No network call at build time.

    Args:
        settings (Settings): Workspace settings. The acceptance-criteria field
            comes from ``settings.jira``.
        connection_store: Grant store. Defaults to the configured token file.
        gateway: OAuth gateway. Defaults to the HTTP Atlassian gateway.
        client_factory: Cloud issue client factory.

    Returns:
        JiraCloudTestDesignSource: The registered ``jira`` source.
    """
    from composition.jira.cloud import _connection_store, _gateway

    return JiraCloudTestDesignSource(
        connection_store=(
            connection_store
            if connection_store is not None
            else _connection_store(settings)
        ),
        gateway=_gateway(settings, gateway),
        client_factory=client_factory,
        acceptance_criteria_field=settings.jira.acceptance_criteria_field,
    )


class _NeutralCloudReader:
    """Refresh through the existing grant helper and translate every failure."""

    def __init__(self, source: JiraCloudTestDesignSource) -> None:
        self._source = source

    def fetch(self, locator: SourceLocator) -> SourceDocument:
        connection = self._source._require_connection()
        site = connection.site
        assert site is not None
        cloud_id = site.cloud_id
        field = self._source._acceptance_criteria_field

        def _fetch(token: str) -> SourceDocument:
            reader = JiraCloudIssueSourceReader(
                self._source._client(token, cloud_id),
                acceptance_criteria_field=field,
            )
            return reader.fetch(locator)

        try:
            document = _with_access_token(
                self._source._connection_store,
                connection,
                self._source._gateway,
                _fetch,
            )
        except JiraReauthorizationRequiredError:
            failure: Exception = SourceReauthorizationRequiredError(_REJECTED)
        except JiraNotConnectedError:
            failure = SourceNotConnectedError(_NOT_CONNECTED)
        except JiraConnectorError:
            failure = ConnectorError(_REQUEST_FAILED)
        except JiraIssueEmptyEvidenceError:
            failure = InsufficientEvidenceError(_NO_EVIDENCE)
        except JiraIssuePayloadError:
            failure = TestDesignValidationError(_INVALID_REQUEST)
        except ConnectorNotFoundError:
            failure = SourceItemNotFoundError(_NOT_FOUND)
        except ConnectorError as error:
            failure = _neutral_connector_error(error)
        else:
            bounded = budget_evidence_text(document.content)
            if bounded == document.content:
                return document
            return SourceDocument(document.metadata, bounded)
        raise failure from None


def _neutral_connector_error(error: ConnectorError) -> Exception:
    if isinstance(error, ConnectorAuthError):
        return SourceReauthorizationRequiredError(_REJECTED)
    for error_type, message in _TRANSPORT_ERRORS:
        if isinstance(error, error_type):
            return error_type(message)
    return ConnectorError(_REQUEST_FAILED)
