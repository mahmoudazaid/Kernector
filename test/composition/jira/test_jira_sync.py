"""Jira status and OAuth sync composition — fake Atlassian, in-memory stores."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from application.contracts import IngestRequest, IngestResponse
from application.errors import (
    JiraReauthorizationRequiredError,
    JiraSelectionRequiredError,
    JiraSiteSelectionRequiredError,
)
from composition import (
    JiraConnectorSyncError,
    JiraIssueLimitExceededError,
    jira_status,
    sync_jira_oauth,
)
from composition import container as composition_container
from domain.errors import ConnectorUnavailableError
from domain.knowledge import CatalogDocument, CatalogStatus, SourceReference, SourceType
from infrastructure.config import load_settings
from infrastructure.connectors.jira.client import JiraIssuePage
from test.composition.jira.jira_fakes import (
    BETA,
    SECRET,
    FakeGateway,
    FakeJiraClient,
    connection,
    issue,
    jira_settings,
    resource,
    stores,
)
from test.document_doubles import InMemoryDocumentCatalog
from test.doubles import InMemoryVectorStore

NOW = datetime(2026, 9, 1, tzinfo=UTC)


class RecordingIngest:
    def __init__(self) -> None:
        self.requests: list[IngestRequest] = []

    def execute(self, request: IngestRequest) -> IngestResponse:
        self.requests.append(request)
        return IngestResponse(
            accepted_ids=[document.source_id for document in request.documents],
            chunk_count=1,
        )


@pytest.fixture
def settings(tmp_path: Path):
    return jira_settings(load_settings(), tmp_path)


@pytest.fixture
def ingest(monkeypatch: pytest.MonkeyPatch) -> RecordingIngest:
    recorder = RecordingIngest()
    monkeypatch.setattr(
        composition_container,
        "build_ingest_knowledge",
        lambda _settings, *, vector_store=None: recorder,
    )
    return recorder


def _row(source_id: str, *, status: CatalogStatus = CatalogStatus.READY) -> CatalogDocument:
    return CatalogDocument(
        reference=SourceReference(source_id, SourceType.JIRA),
        file_name="x.md",
        title="x",
        content_format="markdown",
        status=status,
        created_at=NOW,
        updated_at=NOW,
        chunk_count=1,
        error=None,
        revision="r",
        connector_id="conn-1",
    )


def _sync(settings, tokens, *, gateway=None, client=None, catalog=None):
    return sync_jira_oauth(
        settings,
        connection_store=tokens,
        gateway=gateway or FakeGateway(),
        client_factory=(client or FakeJiraClient()).factory,
        catalog=catalog if catalog is not None else InMemoryDocumentCatalog(),
        vector_store=InMemoryVectorStore(),
    )


# --- status -----------------------------------------------------------------


def test_status_disconnected(settings) -> None:
    status = jira_status(settings, catalog=InMemoryDocumentCatalog())

    assert status.connected is False
    assert status.oauth_ready is True
    assert status.connection_state == "disconnected"
    assert status.document_count == 0


@pytest.mark.parametrize(
    ("overrides", "state"),
    [
        ({"site": None, "project_keys": ()}, "site_selection_required"),
        ({"project_keys": ()}, "setup_required"),
        ({}, "ready"),
        (
            {"access_token": None, "refresh_token": None, "reauthorization_required": True},
            "reauthorization_required",
        ),
    ],
)
def test_status_connection_states(settings, overrides, state) -> None:
    _, tokens = stores(settings)
    tokens.save(connection(**overrides))

    status = jira_status(settings, catalog=InMemoryDocumentCatalog())

    assert status.connected is True
    assert status.connection_state == state


def test_status_reports_site_scope_counts_and_last_sync(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(
        connection(
            project_keys=("ENG", "OPS"),
            last_synced_at="2026-09-01T00:00:00+00:00",
            last_sync_new=1,
            last_sync_updated=2,
            last_sync_unchanged=3,
            last_sync_removed=4,
            last_sync_failed=0,
        )
    )
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("cloud-acme/ENG:ENG-1"))
    catalog.upsert(_row("cloud-acme/ENG:ENG-2", status=CatalogStatus.FAILED))

    status = jira_status(settings, catalog=catalog)

    assert status.site is not None
    assert status.site.url == "https://acme.atlassian.net"
    assert status.account_name == "Ada"
    assert status.project_keys == ("ENG", "OPS")
    assert status.sync_scope == "Acme · ENG, OPS"
    assert status.document_count == 1
    assert status.last_sync is not None
    assert status.last_sync.removed_count == 4
    assert SECRET not in repr(status)


# --- sync -------------------------------------------------------------------


def test_sync_requires_site_then_projects(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection(site=None, project_keys=()))
    with pytest.raises(JiraSiteSelectionRequiredError):
        _sync(settings, tokens)

    tokens.save(connection(project_keys=()))
    with pytest.raises(JiraSelectionRequiredError):
        _sync(settings, tokens)


def test_sync_ingests_reconciles_and_records_last_sync(settings, ingest) -> None:
    _, tokens = stores(settings)
    tokens.save(connection(project_keys=("ENG", "OPS")))
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("cloud-acme/ENG:ENG-OLD"))

    response = _sync(settings, tokens, catalog=catalog)

    assert response.ingested_count == 2
    assert response.removed_count == 1
    ingested = [d.source_id for r in ingest.requests for d in r.documents]
    assert sorted(ingested) == ["cloud-acme/ENG:ENG-1", "cloud-acme/OPS:OPS-1"]
    assert catalog.get(SourceReference("cloud-acme/ENG:ENG-OLD", SourceType.JIRA)) is None
    stored = tokens.load()
    assert stored is not None
    assert stored.last_sync_new == 2
    assert stored.last_sync_removed == 1
    assert stored.last_synced_at is not None


def test_sync_when_site_access_was_revoked_requires_reauth(settings, ingest) -> None:
    _, tokens = stores(settings)
    tokens.save(connection())
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("cloud-acme/ENG:ENG-OLD"))

    with pytest.raises(JiraReauthorizationRequiredError):
        _sync(settings, tokens, gateway=FakeGateway(resources=[resource(BETA)]), catalog=catalog)

    stored = tokens.load()
    assert stored is not None
    assert stored.reauthorization_required is True
    assert len(catalog.all()) == 1
    assert ingest.requests == []


def test_sync_refreshes_once_after_rejected_search(settings, ingest) -> None:
    _, tokens = stores(settings)
    tokens.save(connection())
    client = FakeJiraClient(rejected={f"{SECRET}-access-0"})
    gateway = FakeGateway()

    response = _sync(settings, tokens, gateway=gateway, client=client)

    assert response.ingested_count == 1
    assert gateway.refresh_calls == [f"{SECRET}-refresh-0"]
    stored = tokens.load()
    assert stored is not None
    assert stored.refresh_token == f"{SECRET}-refresh-1"


def test_sync_retry_still_rejected_requires_reauth(settings, ingest) -> None:
    _, tokens = stores(settings)
    tokens.save(connection())
    client = FakeJiraClient(rejected={f"{SECRET}-access-0", f"{SECRET}-access-1"})

    with pytest.raises(JiraReauthorizationRequiredError):
        _sync(settings, tokens, client=client)

    stored = tokens.load()
    assert stored is not None
    assert stored.reauthorization_required is True
    assert stored.access_token is None


def test_sync_over_issue_limit_changes_nothing(tmp_path: Path, ingest) -> None:
    settings = jira_settings(load_settings(), tmp_path, max_issues=1)
    _, tokens = stores(settings)
    tokens.save(connection())
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("cloud-acme/ENG:ENG-OLD"))
    client = FakeJiraClient(projects={"ENG": [issue("ENG-1"), issue("ENG-2")]})

    with pytest.raises(JiraIssueLimitExceededError) as raised:
        _sync(settings, tokens, client=client, catalog=catalog)

    assert "issue limit" in str(raised.value)
    assert len(catalog.all()) == 1
    assert ingest.requests == []


def test_sync_with_repeated_page_token_changes_nothing(settings, ingest) -> None:
    class LoopingClient(FakeJiraClient):
        def factory(self, access_token, cloud_id):
            bound = super().factory(access_token, cloud_id)

            def _search(jql, fields, page_size, next_page_token):
                return JiraIssuePage(issues=(issue("ENG-1"),), next_page_token="same", is_last=False)

            bound.search_issues = _search  # type: ignore[method-assign]
            return bound

    _, tokens = stores(settings)
    tokens.save(connection())
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("cloud-acme/ENG:ENG-OLD"))

    with pytest.raises(JiraConnectorSyncError):
        _sync(settings, tokens, client=LoopingClient(), catalog=catalog)

    assert len(catalog.all()) == 1


def test_sync_provider_failure_is_sanitized(
    settings, ingest, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    _, tokens = stores(settings)
    tokens.save(connection())
    client = FakeJiraClient(error=ConnectorUnavailableError(f"upstream {SECRET}"))

    with pytest.raises(JiraConnectorSyncError) as raised:
        _sync(settings, tokens, client=client)

    assert str(raised.value) == "The Jira connector sync failed."
    assert SECRET not in caplog.text
    stored = tokens.load()
    assert stored is not None
    assert stored.reauthorization_required is False
