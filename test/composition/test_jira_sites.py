"""Explicit Jira site selection for multi-site Atlassian grants."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from application.errors import InputRejectedError
from composition import put_jira_site
from domain.knowledge import CatalogDocument, CatalogStatus, SourceReference, SourceType
from infrastructure.config import load_settings
from test.composition.jira_fakes import (
    ACME,
    BETA,
    FakeGateway,
    connection,
    jira_settings,
    resource,
    stores,
)
from test.document_doubles import InMemoryDocumentCatalog
from test.doubles import InMemoryVectorStore


@pytest.fixture
def settings(tmp_path: Path):
    return jira_settings(load_settings(), tmp_path)


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


def test_select_site_from_many(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection(site=None, project_keys=()))
    gateway = FakeGateway(resources=[resource(ACME), resource(BETA)])

    selection = put_jira_site(
        settings, cloud_id="cloud-beta", connection_store=tokens, gateway=gateway
    )

    assert selection.site is not None
    assert selection.site.cloud_id == "cloud-beta"
    stored = tokens.load()
    assert stored is not None
    assert stored.site == BETA


def test_unknown_site_is_rejected(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection(site=None, project_keys=()))

    with pytest.raises(InputRejectedError):
        put_jira_site(
            settings, cloud_id="cloud-nope", connection_store=tokens, gateway=FakeGateway()
        )

    stored = tokens.load()
    assert stored is not None
    assert stored.site is None


def test_switching_site_purges_docs_and_clears_projects(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection())
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("cloud-acme/ENG:ENG-1"))

    put_jira_site(
        settings,
        cloud_id="cloud-beta",
        connection_store=tokens,
        gateway=FakeGateway(resources=[resource(ACME), resource(BETA)]),
        catalog=catalog,
        vector_store=InMemoryVectorStore(),
    )

    stored = tokens.load()
    assert stored is not None
    assert stored.project_keys == ()
    assert catalog.all() == ()


def test_reselecting_same_site_keeps_projects_and_docs(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection())
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("cloud-acme/ENG:ENG-1"))

    put_jira_site(
        settings,
        cloud_id="cloud-acme",
        connection_store=tokens,
        gateway=FakeGateway(),
        catalog=catalog,
    )

    stored = tokens.load()
    assert stored is not None
    assert stored.project_keys == ("ENG",)
    assert len(catalog.all()) == 1
