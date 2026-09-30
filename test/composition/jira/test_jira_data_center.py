"""Jira Data Center composition through the public Jira functions; offline fakes only."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from application.contracts import IngestRequest, IngestResponse
from application.errors import (
    InputRejectedError,
    JiraDataCenterCredentialsRejectedError,
    JiraDataCenterModeError,
    JiraReauthorizationRequiredError,
    JiraSelectionRequiredError,
    JiraSetupRequiredError,
)
from composition import container as composition_container
from composition import (
    complete_jira_oauth,
    disconnect_jira_oauth,
    get_jira_selection,
    jira_status,
    list_jira_projects,
    list_jira_sites,
    put_jira_selection,
    put_jira_site,
    start_jira_oauth,
    sync_jira_oauth,
)
from composition.errors import (
    JiraConnectorError,
    JiraConnectorSyncError,
    JiraIssueLimitExceededError,
)
from domain.errors import ConnectorNotFoundError, ConnectorUnavailableError
from domain.knowledge import CatalogDocument, CatalogStatus, SourceReference, SourceType
from infrastructure.config import load_settings
from infrastructure.connectors.jira.client import JiraIssuePage
from infrastructure.connectors.jira.data_center_state import JiraDataCenterState
from test.composition.jira.jira_fakes import (
    DC_BASE_URL,
    DC_OTHER_SITE,
    DC_SITE,
    DC_TOKEN,
    FakeDataCenterClient,
    dc_settings,
    dc_store,
    issue,
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
    return dc_settings(load_settings(), tmp_path)


@pytest.fixture
def ingest(monkeypatch: pytest.MonkeyPatch) -> RecordingIngest:
    recorder = RecordingIngest()
    monkeypatch.setattr(
        composition_container,
        "build_ingest_knowledge",
        lambda _settings, *, vector_store=None: recorder,
    )
    return recorder


@pytest.fixture(autouse=True)
def _no_real_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("tests must inject a fake Data Center client")

    monkeypatch.setattr(
        "infrastructure.connectors.jira.data_center.HttpJiraDataCenterClient", _refuse
    )


def _row(
    source_id: str,
    *,
    connector_id: str = "conn-dc",
    status: CatalogStatus = CatalogStatus.READY,
) -> CatalogDocument:
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
        connector_id=connector_id,
    )


def _saved(settings, **overrides: object) -> None:
    values: dict[str, object] = {
        "connector_id": "conn-dc",
        "site": DC_SITE,
        "project_keys": ("ENG",),
    }
    values.update(overrides)
    dc_store(settings).mutate(lambda _current: JiraDataCenterState(**values))  # type: ignore[arg-type]


# --- status -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("base_url", "token"),
    [(DC_BASE_URL, None), (None, DC_TOKEN)],
)
def test_status_with_partial_configuration_requires_setup(
    tmp_path: Path, base_url: str | None, token: str | None
) -> None:
    settings = dc_settings(load_settings(), tmp_path, base_url=base_url, token=token)

    status = jira_status(settings, catalog=InMemoryDocumentCatalog())

    assert status.mode == "data_center"
    assert status.connected is False
    assert status.oauth_ready is False
    assert status.setup_required is True
    assert status.connection_state == "setup_required"


def test_status_configured_without_projects_requires_project_setup(settings) -> None:
    status = jira_status(settings, catalog=InMemoryDocumentCatalog())

    assert status.mode == "data_center"
    assert status.connected is True
    assert status.setup_required is True
    assert status.reauthorization_required is False
    assert status.connection_state == "setup_required"


def test_status_ready_reports_instance_scope_and_only_this_connectors_documents(
    settings,
) -> None:
    _saved(
        settings,
        project_keys=("ENG", "OPS"),
        last_synced_at="2026-09-01T00:00:00+00:00",
        last_sync_new=1,
        last_sync_updated=0,
        last_sync_unchanged=2,
        last_sync_removed=0,
        last_sync_failed=0,
    )
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("SRV-1/ENG:ENG-1"))
    catalog.upsert(_row("SRV-1/ENG:ENG-2", status=CatalogStatus.FAILED))
    catalog.upsert(_row("cloud-acme/ENG:ENG-9", connector_id="conn-cloud"))

    status = jira_status(settings, catalog=catalog)

    assert status.connection_state == "ready"
    assert status.setup_required is False
    assert status.site is not None
    assert status.site.instance_id == "SRV-1"
    assert status.site.cloud_id is None
    assert status.site.url == DC_BASE_URL
    assert status.sync_scope == "Example Jira · ENG, OPS"
    assert status.document_count == 1
    assert status.last_sync is not None
    assert status.last_sync.unchanged_count == 2
    assert DC_TOKEN not in repr(status)


def test_status_after_rejected_token_requires_reauthorization_and_setup(settings) -> None:
    _saved(settings, credentials_rejected=True)

    status = jira_status(settings, catalog=InMemoryDocumentCatalog())

    assert status.connection_state == "reauthorization_required"
    assert status.reauthorization_required is True
    assert status.setup_required is True
    assert status.connected is True


def test_cloud_status_reports_cloud_mode(tmp_path: Path) -> None:
    settings = replace(load_settings(), jira_data_center=None)

    assert jira_status(settings, catalog=InMemoryDocumentCatalog()).mode == "cloud"


# --- Cloud-only operations and setup -----------------------------------------


def test_cloud_only_operations_raise_data_center_mode(settings) -> None:
    with pytest.raises(JiraDataCenterModeError):
        start_jira_oauth(settings)
    with pytest.raises(JiraDataCenterModeError):
        complete_jira_oauth(settings, state="s", code="c", error=None)
    with pytest.raises(JiraDataCenterModeError):
        list_jira_sites(settings)
    with pytest.raises(JiraDataCenterModeError):
        put_jira_site(settings, cloud_id="cloud-acme")


def test_unconfigured_operations_raise_setup_required(tmp_path: Path) -> None:
    settings = dc_settings(load_settings(), tmp_path, token=None)
    fake = FakeDataCenterClient()

    for call in (
        lambda: list_jira_projects(settings, client_factory=fake.factory),
        lambda: get_jira_selection(settings),
        lambda: put_jira_selection(
            settings, project_keys=["ENG"], client_factory=fake.factory
        ),
        lambda: sync_jira_oauth(
            settings, catalog=InMemoryDocumentCatalog(), client_factory=fake.factory
        ),
    ):
        with pytest.raises(JiraSetupRequiredError):
            call()
    assert fake.built == []


# --- projects -----------------------------------------------------------------


def test_projects_list_without_site_selection_using_configured_url_and_token(
    settings,
) -> None:
    fake = FakeDataCenterClient()

    page = list_jira_projects(settings, client_factory=fake.factory)

    assert [item.key for item in page.items] == ["ENG", "OPS"]
    assert page.next_start_at is None
    assert fake.built == [(DC_BASE_URL, DC_TOKEN)]


def test_projects_reject_negative_start(settings) -> None:
    with pytest.raises(InputRejectedError):
        list_jira_projects(settings, start_at=-1, client_factory=FakeDataCenterClient().factory)


def test_projects_not_found_means_url_is_not_a_jira_api(settings) -> None:
    fake = FakeDataCenterClient(error=ConnectorNotFoundError("404"))

    with pytest.raises(JiraSetupRequiredError):
        list_jira_projects(settings, client_factory=fake.factory)


def test_projects_upstream_failure_is_a_fixed_connector_error(settings) -> None:
    fake = FakeDataCenterClient(error=ConnectorUnavailableError(f"boom {DC_TOKEN}"))

    with pytest.raises(JiraConnectorError) as caught:
        list_jira_projects(settings, client_factory=fake.factory)

    assert DC_TOKEN not in str(caught.value)


# --- selection ------------------------------------------------------------------


def test_selection_saves_instance_identity_and_connector_without_token(settings) -> None:
    fake = FakeDataCenterClient()

    selection = put_jira_selection(
        settings, project_keys=["eng", "ENG"], client_factory=fake.factory
    )

    assert selection.project_keys == ("ENG",)
    assert selection.site is not None
    assert selection.site.instance_id == "SRV-1"
    assert selection.site.cloud_id is None
    assert selection.connector_id
    saved = dc_store(settings).load()
    assert saved is not None
    assert saved.site == DC_SITE
    assert saved.connector_id == selection.connector_id
    assert get_jira_selection(settings) == selection
    assert DC_TOKEN not in settings.jira_data_center.state_path.read_text()


def test_selection_with_inaccessible_project_is_rejected(settings) -> None:
    fake = FakeDataCenterClient()

    with pytest.raises(InputRejectedError):
        put_jira_selection(settings, project_keys=["NOPE"], client_factory=fake.factory)

    assert dc_store(settings).load() is None


def test_selection_rejects_invalid_keys_before_network(settings) -> None:
    fake = FakeDataCenterClient()

    with pytest.raises(InputRejectedError):
        put_jira_selection(settings, project_keys=["bad key"], client_factory=fake.factory)

    assert fake.request_count == 0


def test_selection_purges_only_deselected_projects_of_this_connector(settings) -> None:
    _saved(settings, project_keys=("ENG", "OPS"))
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("SRV-1/ENG:ENG-1"))
    catalog.upsert(_row("SRV-1/OPS:OPS-1"))
    catalog.upsert(_row("SRV-1/OPS:OPS-2", connector_id="someone-else"))
    store = InMemoryVectorStore()

    put_jira_selection(
        settings,
        project_keys=["ENG"],
        client_factory=FakeDataCenterClient().factory,
        catalog=catalog,
        vector_store=store,
    )

    assert sorted(row.reference.source_id for row in catalog.all()) == [
        "SRV-1/ENG:ENG-1",
        "SRV-1/OPS:OPS-2",
    ]


def test_empty_selection_saves_without_network_and_purges_all_projects(settings) -> None:
    _saved(settings, project_keys=("ENG",))
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("SRV-1/ENG:ENG-1"))
    fake = FakeDataCenterClient()

    selection = put_jira_selection(
        settings,
        project_keys=[],
        client_factory=fake.factory,
        catalog=catalog,
        vector_store=InMemoryVectorStore(),
    )

    assert selection.project_keys == ()
    assert fake.request_count == 0
    assert list(catalog.all()) == []


def test_selection_on_changed_server_id_purges_old_instance_documents(settings) -> None:
    _saved(settings, project_keys=("ENG",))
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("SRV-1/ENG:ENG-1"))
    fake = FakeDataCenterClient(site=DC_OTHER_SITE)

    selection = put_jira_selection(
        settings,
        project_keys=["ENG"],
        client_factory=fake.factory,
        catalog=catalog,
        vector_store=InMemoryVectorStore(),
    )

    assert selection.site is not None
    assert selection.site.instance_id == "SRV-2"
    assert list(catalog.all()) == []


# --- sync -------------------------------------------------------------------------


def test_sync_requires_projects(settings) -> None:
    with pytest.raises(JiraSelectionRequiredError):
        sync_jira_oauth(
            settings,
            catalog=InMemoryDocumentCatalog(),
            client_factory=FakeDataCenterClient().factory,
        )


def test_sync_ingests_wiki_markdown_scoped_to_instance_and_connector(
    settings, ingest: RecordingIngest
) -> None:
    _saved(settings, project_keys=("ENG",))
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("SRV-1/ENG:ENG-OLD"))
    catalog.upsert(_row("SRV-9/ENG:ENG-OTHER"))
    catalog.upsert(_row("SRV-1/ENG:ENG-FOREIGN", connector_id="someone-else"))
    wiki_issue = issue("ENG-1")
    wiki_issue["fields"]["description"] = "h2. Steps\n* *bold* step"  # type: ignore[index]
    fake = FakeDataCenterClient(projects={"ENG": [wiki_issue]})

    result = sync_jira_oauth(
        settings,
        catalog=catalog,
        vector_store=InMemoryVectorStore(),
        client_factory=fake.factory,
    )

    assert result.ingested_count == 1
    assert result.removed_count == 1
    [request] = ingest.requests
    [document] = request.documents
    assert document.source_id == "SRV-1/ENG:ENG-1"
    assert "## Steps" in document.content
    assert "- **bold** step" in document.content
    assert document.metadata.extra["jira_instance_id"] == "SRV-1"
    assert "cloud_id" not in document.metadata.extra
    assert document.metadata.extra["connector_id"] == "conn-dc"
    assert document.metadata.extra["jira_issue_url"] == f"{DC_BASE_URL}/browse/ENG-1"
    assert sorted(row.reference.source_id for row in catalog.all()) == [
        "SRV-1/ENG:ENG-1",
        "SRV-1/ENG:ENG-FOREIGN",
        "SRV-9/ENG:ENG-OTHER",
    ]
    assert DC_TOKEN not in repr(list(catalog.all()))
    saved = dc_store(settings).load()
    assert saved is not None
    assert saved.last_sync_new == 1
    assert saved.last_sync_removed == 1
    assert jira_status(settings, catalog=catalog).last_sync is not None
    assert DC_TOKEN not in repr(request)
    assert DC_TOKEN not in settings.jira_data_center.state_path.read_text()


def test_sync_aborts_before_writes_when_total_changes_between_pages(
    settings, ingest: RecordingIngest
) -> None:
    _saved(settings, project_keys=("ENG",))
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("SRV-1/ENG:ENG-OLD"))
    fake = FakeDataCenterClient(
        pages={
            "ENG": [
                JiraIssuePage(
                    issues=(issue("ENG-1"),), next_page_token="1", is_last=False, total=100
                ),
                JiraIssuePage(
                    issues=(issue("ENG-2"),), next_page_token="2", is_last=False, total=90
                ),
            ]
        }
    )

    with pytest.raises(JiraConnectorSyncError):
        sync_jira_oauth(
            settings,
            catalog=catalog,
            vector_store=InMemoryVectorStore(),
            client_factory=fake.factory,
        )

    assert ingest.requests == []
    assert [row.reference.source_id for row in catalog.all()] == ["SRV-1/ENG:ENG-OLD"]
    saved = dc_store(settings).load()
    assert saved is not None and saved.last_synced_at is None


def test_sync_over_issue_limit_aborts_before_writes(
    tmp_path: Path, ingest: RecordingIngest
) -> None:
    settings = dc_settings(load_settings(), tmp_path, max_issues=1)
    _saved(settings, project_keys=("ENG",))
    catalog = InMemoryDocumentCatalog()
    fake = FakeDataCenterClient(projects={"ENG": [issue("ENG-1"), issue("ENG-2")]})

    with pytest.raises(JiraIssueLimitExceededError):
        sync_jira_oauth(
            settings,
            catalog=catalog,
            vector_store=InMemoryVectorStore(),
            client_factory=fake.factory,
        )

    assert ingest.requests == []
    assert list(catalog.all()) == []


def test_sync_on_changed_server_id_purges_and_requires_new_selection(
    settings, ingest: RecordingIngest
) -> None:
    _saved(settings, project_keys=("ENG",))
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("SRV-1/ENG:ENG-1"))
    fake = FakeDataCenterClient(site=DC_OTHER_SITE)

    with pytest.raises(JiraSelectionRequiredError):
        sync_jira_oauth(
            settings,
            catalog=catalog,
            vector_store=InMemoryVectorStore(),
            client_factory=fake.factory,
        )

    assert ingest.requests == []
    assert list(catalog.all()) == []
    saved = dc_store(settings).load()
    assert saved is not None
    assert saved.project_keys == ()
    assert saved.site == DC_OTHER_SITE


def test_sync_upstream_failure_is_a_fixed_sync_error(settings, ingest) -> None:
    _saved(settings)
    fake = FakeDataCenterClient(
        server_info_error=ConnectorUnavailableError(f"HTTP 500 {DC_TOKEN}")
    )

    with pytest.raises(JiraConnectorSyncError) as caught:
        sync_jira_oauth(
            settings,
            catalog=InMemoryDocumentCatalog(),
            vector_store=InMemoryVectorStore(),
            client_factory=fake.factory,
        )

    assert DC_TOKEN not in str(caught.value)


# --- rejected token and recovery -----------------------------------------------


@pytest.mark.parametrize("operation", ["projects", "selection", "sync"])
def test_rejected_token_marks_state_and_raises_reauthorization(
    settings, ingest, operation: str
) -> None:
    _saved(settings)
    fake = FakeDataCenterClient(reject=True)
    calls = {
        "projects": lambda: list_jira_projects(settings, client_factory=fake.factory),
        "selection": lambda: put_jira_selection(
            settings, project_keys=["ENG"], client_factory=fake.factory
        ),
        "sync": lambda: sync_jira_oauth(
            settings,
            catalog=InMemoryDocumentCatalog(),
            vector_store=InMemoryVectorStore(),
            client_factory=fake.factory,
        ),
    }

    with pytest.raises(JiraDataCenterCredentialsRejectedError) as caught:
        calls[operation]()

    assert isinstance(caught.value, JiraReauthorizationRequiredError)
    assert DC_TOKEN not in str(caught.value)
    saved = dc_store(settings).load()
    assert saved is not None
    assert saved.credentials_rejected is True
    assert saved.project_keys == ("ENG",)
    assert jira_status(settings, catalog=InMemoryDocumentCatalog()).connection_state == (
        "reauthorization_required"
    )


def test_rejected_token_without_saved_state_is_still_reported(settings) -> None:
    fake = FakeDataCenterClient(reject=True)

    with pytest.raises(JiraDataCenterCredentialsRejectedError):
        list_jira_projects(settings, client_factory=fake.factory)

    status = jira_status(settings, catalog=InMemoryDocumentCatalog())
    assert status.reauthorization_required is True


def test_successful_authenticated_request_clears_rejection(settings) -> None:
    _saved(settings, credentials_rejected=True)

    list_jira_projects(settings, client_factory=FakeDataCenterClient().factory)

    saved = dc_store(settings).load()
    assert saved is not None
    assert saved.credentials_rejected is False
    assert jira_status(settings, catalog=InMemoryDocumentCatalog()).connection_state == (
        "ready"
    )


# --- disconnect ----------------------------------------------------------------------


def test_disconnect_clears_state_and_connector_documents_but_not_the_token(
    settings,
) -> None:
    _saved(settings)
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("SRV-1/ENG:ENG-1"))
    catalog.upsert(_row("SRV-1/ENG:ENG-2", connector_id="someone-else"))

    disconnect_jira_oauth(settings, catalog=catalog, vector_store=InMemoryVectorStore())

    assert dc_store(settings).load() is None
    assert not settings.jira_data_center.state_path.exists()
    assert [row.reference.source_id for row in catalog.all()] == ["SRV-1/ENG:ENG-2"]
    assert settings.jira_data_center.token == DC_TOKEN
    status = jira_status(settings, catalog=catalog)
    assert status.connected is True
    assert status.connection_state == "setup_required"


def test_disconnect_without_state_is_a_no_op(settings) -> None:
    disconnect_jira_oauth(settings, catalog=InMemoryDocumentCatalog())

    assert dc_store(settings).load() is None


def test_state_json_is_private_and_token_free(settings) -> None:
    put_jira_selection(
        settings, project_keys=["ENG"], client_factory=FakeDataCenterClient().factory
    )

    path = settings.jira_data_center.state_path
    assert path.stat().st_mode & 0o777 == 0o600
    payload = json.loads(path.read_text())
    assert DC_TOKEN not in json.dumps(payload)
    assert "token" not in json.dumps(payload).lower()
    assert payload["site"] == {
        "instance_id": "SRV-1",
        "site_url": DC_BASE_URL,
        "name": "Example Jira",
    }
