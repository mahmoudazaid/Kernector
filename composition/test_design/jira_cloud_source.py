"""Jira Cloud issues as a Test Design source (Atlassian OAuth 2.0 grant).

Every failure leaving the reader is a freshly built provider-neutral error with
no cause or context, so Jira diagnostics (response bodies, URLs, site names)
never reach responses or logged tracebacks.
"""

from __future__ import annotations

from collections.abc import Callable

from application.errors import (
    InsufficientEvidenceError,
    JiraNotConnectedError,
    JiraReauthorizationRequiredError,
    JiraSiteSelectionRequiredError,
    SourceItemNotFoundError,
    SourceNotConnectedError,
    SourceReauthorizationRequiredError,
)
from composition.errors import JiraConnectorError
from composition.jira.cloud import (
    call_with_jira_cloud_token,
    require_jira_cloud_site,
    saved_jira_cloud_scope,
)
from composition.test_design.errors import TestDesignValidationError
from composition.test_design.jira_errors import (
    INVALID_LOCATOR,
    INVALID_REQUEST,
    NO_EVIDENCE,
    NOT_CONNECTED,
    NOT_FOUND,
    REJECTED,
    REQUEST_FAILED,
    neutral_connector_error,
)
from composition.test_design.sources import AmbiguousSourceLocatorError
from domain.errors import ConnectorError, ConnectorNotFoundError
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
    JiraCloudIssueSourceReader,
    JiraIssueClient,
    JiraIssueEmptyEvidenceError,
    JiraIssuePayloadError,
)

JiraCloudClientFactory = Callable[[str, str], JiraIssueClient]


class JiraCloudTestDesignSource:
    """``TestDesignSource`` over a single live Jira Cloud issue.

    Browse URLs are accepted only for the grant's selected site. Bare keys are
    extracted from chat text only for the saved Hub projects. ``canonicalize``
    and ``extract_locator`` read the local grant file and never call Atlassian.
    """

    provider = "jira"

    def __init__(
        self,
        *,
        settings: Settings,
        client_factory: JiraCloudClientFactory,
        connection_store=None,
        oauth_gateway=None,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._connection_store = connection_store
        self._oauth_gateway = oauth_gateway

    def canonicalize(self, locator: str) -> str:
        site, _project_keys = self._scope()
        try:
            return canonicalize_jira_issue_locator(locator, base=_browse_base(site))
        except InvalidJiraIssueLocatorError as error:
            raise TestDesignValidationError(INVALID_LOCATOR) from error

    def extract_locator(self, text: str) -> str | None:
        site, project_keys = self._scope()
        try:
            return extract_jira_issue_locator(
                text, base=_browse_base(site), project_keys=project_keys
            )
        except AmbiguousJiraIssueLocatorError as error:
            raise AmbiguousSourceLocatorError(str(error)) from error

    def reader(self) -> LiveSourceReader:
        try:
            require_jira_cloud_site(
                self._settings, connection_store=self._connection_store
            )
        except JiraReauthorizationRequiredError:
            failure: Exception = SourceReauthorizationRequiredError(REJECTED)
        except (JiraNotConnectedError, JiraSiteSelectionRequiredError):
            failure = SourceNotConnectedError(NOT_CONNECTED)
        else:
            return _CloudIssueReader(self._fetch)
        raise failure from None

    def _scope(self):
        return saved_jira_cloud_scope(
            self._settings, connection_store=self._connection_store
        )

    def _fetch(self, locator: SourceLocator) -> SourceDocument:
        def read(access_token: str, site) -> SourceDocument:
            client = self._client_factory(access_token, site.cloud_id)
            return JiraCloudIssueSourceReader(
                client,
                acceptance_criteria_field=self._settings.jira.acceptance_criteria_field,
            ).fetch(locator)

        return call_with_jira_cloud_token(
            self._settings,
            read,
            connection_store=self._connection_store,
            gateway=self._oauth_gateway,
        )


def build_jira_cloud_test_design_source(
    settings: Settings,
    *,
    connection_store=None,
    oauth_gateway=None,
    client_factory: JiraCloudClientFactory | None = None,
) -> JiraCloudTestDesignSource:
    """Build the source over the stored Atlassian grant and the Cloud HTTP client."""

    def http_client(access_token: str, cloud_id: str) -> JiraIssueClient:
        from infrastructure.connectors.jira.client import HttpJiraClient

        return HttpJiraClient(access_token, cloud_id)

    return JiraCloudTestDesignSource(
        settings=settings,
        client_factory=client_factory if client_factory is not None else http_client,
        connection_store=connection_store,
        oauth_gateway=oauth_gateway,
    )


class _CloudIssueReader:
    """Translate every Jira Cloud failure to a neutral error."""

    def __init__(self, fetch: Callable[[SourceLocator], SourceDocument]) -> None:
        self._fetch = fetch

    def fetch(self, locator: SourceLocator) -> SourceDocument:
        try:
            return self._fetch(locator)
        except JiraReauthorizationRequiredError:
            failure: Exception = SourceReauthorizationRequiredError(REJECTED)
        except (JiraNotConnectedError, JiraSiteSelectionRequiredError):
            failure = SourceNotConnectedError(NOT_CONNECTED)
        except JiraConnectorError:
            failure = ConnectorError(REQUEST_FAILED)
        except JiraIssueEmptyEvidenceError:
            failure = InsufficientEvidenceError(NO_EVIDENCE)
        except JiraIssuePayloadError:
            failure = TestDesignValidationError(INVALID_REQUEST)
        except ConnectorNotFoundError:
            failure = SourceItemNotFoundError(NOT_FOUND)
        except ConnectorError as error:
            failure = neutral_connector_error(error)
        # Raised outside the handler so the Jira error is not kept as __context__.
        raise failure from None


def _browse_base(site) -> JiraBrowseBase | None:
    return None if site is None else JiraBrowseBase.parse(site.site_url)
