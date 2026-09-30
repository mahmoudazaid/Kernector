"""Jira OAuth start/callback composition — fake gateway, no live credentials."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from application.errors import JiraNotConnectedError
from composition import (
    complete_jira_oauth,
    disconnect_jira_oauth,
    start_jira_oauth,
)
from domain.knowledge import CatalogDocument, CatalogStatus, SourceReference, SourceType
from infrastructure.config import load_settings
from infrastructure.connectors.jira.oauth import JiraOAuthTransportError
from test.composition.jira.jira_fakes import (
    ACME,
    BETA,
    SECRET,
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


def _callback(settings, gateway: FakeGateway, **overrides):
    states, tokens = stores(settings)
    kwargs = {
        "state": states.issue(),
        "code": "code",
        "error": None,
        "state_store": states,
        "connection_store": tokens,
        "gateway": gateway,
    }
    kwargs.update(overrides)
    return complete_jira_oauth(settings, **kwargs), tokens


def test_start_without_client_redirects_unconfigured(tmp_path: Path) -> None:
    settings = jira_settings(load_settings(), tmp_path)
    from dataclasses import replace

    settings = replace(settings, jira_oauth=replace(settings.jira_oauth, client_id=None))

    assert start_jira_oauth(settings).endswith("jira=unconfigured")


def test_start_returns_atlassian_url_with_issued_state(settings) -> None:
    states, _ = stores(settings)

    url = start_jira_oauth(settings, state_store=states)

    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://auth.atlassian.com/authorize?")
    assert states.consume(query["state"][0]) is True


def test_callback_denied(settings) -> None:
    url, tokens = _callback(settings, FakeGateway(), error="access_denied", code=None)

    assert url == "http://localhost:3000/documents?jira=denied"
    assert tokens.load() is None


def test_callback_rejects_replayed_state(settings) -> None:
    url, tokens = _callback(settings, FakeGateway(), state="forged")

    assert url.endswith("jira=invalid_state")
    assert tokens.load() is None


def test_callback_exchange_failure_is_error_without_tokens(settings) -> None:
    gateway = FakeGateway(exchange_error=JiraOAuthTransportError("boom"))

    url, tokens = _callback(settings, gateway)

    assert url.endswith("jira=error")
    assert tokens.load() is None


def test_callback_with_zero_jira_sites_stores_nothing(settings) -> None:
    gateway = FakeGateway(resources=[resource(ACME, scopes=("read:confluence-content",))])

    url, tokens = _callback(settings, gateway)

    assert url.endswith("jira=no_site")
    assert tokens.load() is None


def test_callback_with_one_site_auto_selects_it(settings) -> None:
    url, tokens = _callback(settings, FakeGateway())

    assert url == "http://localhost:3000/documents?jira=connected"
    stored = tokens.load()
    assert stored is not None
    assert stored.site == ACME
    assert stored.account_name == "Ada"
    assert stored.project_keys == ()
    assert stored.connector_id
    assert stored.access_token_expires_at is not None
    assert SECRET not in url


def test_callback_with_many_sites_requires_explicit_choice(settings) -> None:
    gateway = FakeGateway(resources=[resource(BETA), resource(ACME)])

    url, tokens = _callback(settings, gateway)

    assert url.endswith("jira=connected")
    stored = tokens.load()
    assert stored is not None
    assert stored.site is None


def test_reconnect_keeps_connector_site_and_projects(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection(reauthorization_required=True, access_token=None, refresh_token=None))

    _callback(settings, FakeGateway(resources=[resource(ACME), resource(BETA)]))

    stored = tokens.load()
    assert stored is not None
    assert stored.connector_id == "conn-1"
    assert stored.site == ACME
    assert stored.project_keys == ("ENG",)
    assert stored.reauthorization_required is False


def _row(source_id: str, connector_id: str = "conn-1") -> CatalogDocument:
    from datetime import UTC, datetime

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
        connector_id=connector_id,
    )


def test_disconnect_clears_grant_and_purges_connector_docs(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection())
    catalog = InMemoryDocumentCatalog()
    mine = _row("cloud-acme/ENG:ENG-1")
    other = _row("cloud-acme/ENG:ENG-2", connector_id="other")
    catalog.upsert(mine)
    catalog.upsert(other)
    store = InMemoryVectorStore()

    disconnect_jira_oauth(
        settings, connection_store=tokens, catalog=catalog, vector_store=store
    )

    assert tokens.load() is None
    assert catalog.get(mine.reference) is None
    assert catalog.get(other.reference) is not None
    with pytest.raises(JiraNotConnectedError):
        disconnect_jira_oauth(settings, connection_store=tokens, catalog=catalog)


def test_disconnect_works_while_reauthorization_required(settings) -> None:
    _, tokens = stores(settings)
    tokens.save(connection(access_token=None, refresh_token=None, reauthorization_required=True))
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("cloud-acme/ENG:ENG-1"))

    disconnect_jira_oauth(
        settings, connection_store=tokens, catalog=catalog, vector_store=InMemoryVectorStore()
    )

    assert tokens.load() is None
    assert catalog.all() == ()
