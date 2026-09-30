"""Jira project picker and selection with deselect-purge."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from application.errors import InputRejectedError, JiraSiteSelectionRequiredError
from composition import (
    JiraConnectorError,
    get_jira_selection,
    list_jira_projects,
    put_jira_selection,
)
from domain.errors import ConnectorUnavailableError
from domain.knowledge import CatalogDocument, CatalogStatus, SourceReference, SourceType
from infrastructure.config import load_settings
from test.composition.jira.jira_fakes import (
    SECRET,
    FakeGateway,
    FakeJiraClient,
    connection,
    jira_settings,
    stores,
)
from test.document_doubles import InMemoryDocumentCatalog
from test.doubles import InMemoryVectorStore


@pytest.fixture
def settings(tmp_path: Path):
    return jira_settings(load_settings(), tmp_path, page_size=1)


def _row(source_id: str) -> CatalogDocument:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    return CatalogDocument(
        reference=SourceReference(source_id, SourceType.JIRA),
        file_name="x.md",
        title="x",
        content_format="markdown",
        status=CatalogStatus.READY,
        created_at=now,
        updated_at=now,
        chunk_count=1,
        error=None,
        revision="r",
        connector_id="conn-1",
    )


def test_projects_page_through_the_selected_site(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection())
    client = FakeJiraClient()

    first = list_jira_projects(
        settings, connection_store=tokens, gateway=FakeGateway(), client_factory=client.factory
    )
    second = list_jira_projects(
        settings,
        start_at=first.next_start_at or 0,
        connection_store=tokens,
        gateway=FakeGateway(),
        client_factory=client.factory,
    )

    assert [p.key for p in first.items] == ["ENG"]
    assert first.next_start_at == 1
    assert [p.key for p in second.items] == ["OPS"]
    assert second.next_start_at is None
    assert client.calls[0] == (f"{SECRET}-access-0", "cloud-acme")


def test_projects_require_a_site(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection(site=None, project_keys=()))

    with pytest.raises(JiraSiteSelectionRequiredError):
        list_jira_projects(
            settings,
            connection_store=tokens,
            gateway=FakeGateway(),
            client_factory=FakeJiraClient().factory,
        )


def test_project_listing_failure_is_sanitized(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection())
    client = FakeJiraClient(error=ConnectorUnavailableError(f"leak {SECRET}"))

    with pytest.raises(JiraConnectorError) as raised:
        list_jira_projects(
            settings, connection_store=tokens, gateway=FakeGateway(), client_factory=client.factory
        )

    assert SECRET not in str(raised.value)


def test_rejected_token_refreshes_for_project_listing(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection())
    client = FakeJiraClient(rejected={f"{SECRET}-access-0"})

    page = list_jira_projects(
        settings, connection_store=tokens, gateway=FakeGateway(), client_factory=client.factory
    )

    assert page.items
    assert client.calls[-1][0] == f"{SECRET}-access-1"


def test_selection_is_validated_normalized_and_saved(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection(project_keys=()))

    selection = put_jira_selection(
        settings,
        project_keys=["ops", " ENG ", "OPS"],
        connection_store=tokens,
        gateway=FakeGateway(),
        client_factory=FakeJiraClient().factory,
        catalog=InMemoryDocumentCatalog(),
    )

    assert selection.project_keys == ("OPS", "ENG")
    assert get_jira_selection(settings, connection_store=tokens).project_keys == ("OPS", "ENG")


@pytest.mark.parametrize("keys", [["NOPE"], ["bad key!"], [""]])
def test_invalid_or_inaccessible_projects_are_rejected(settings, keys) -> None:
    _, tokens = stores(settings)
    tokens.save(connection())

    with pytest.raises(InputRejectedError):
        put_jira_selection(
            settings,
            project_keys=keys,
            connection_store=tokens,
            gateway=FakeGateway(),
            client_factory=FakeJiraClient().factory,
        )

    stored = tokens.load()
    assert stored is not None
    assert stored.project_keys == ("ENG",)


def test_deselecting_a_project_purges_only_its_docs(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection(project_keys=("ENG", "OPS")))
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("cloud-acme/ENG:ENG-1"))
    catalog.upsert(_row("cloud-acme/OPS:OPS-1"))
    catalog.upsert(_row("cloud-acme/ENGX:ENGX-1"))

    put_jira_selection(
        settings,
        project_keys=["OPS"],
        connection_store=tokens,
        gateway=FakeGateway(),
        client_factory=FakeJiraClient(projects={"OPS": []}).factory,
        catalog=catalog,
        vector_store=InMemoryVectorStore(),
    )

    remaining = {row.reference.source_id for row in catalog.all()}
    assert remaining == {"cloud-acme/OPS:OPS-1", "cloud-acme/ENGX:ENGX-1"}


def test_empty_selection_purges_all_selected_projects(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection(project_keys=("ENG",)))
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("cloud-acme/ENG:ENG-1"))

    selection = put_jira_selection(
        settings,
        project_keys=[],
        connection_store=tokens,
        gateway=FakeGateway(),
        client_factory=FakeJiraClient().factory,
        catalog=catalog,
        vector_store=InMemoryVectorStore(),
    )

    assert selection.project_keys == ()
    assert catalog.all() == ()
