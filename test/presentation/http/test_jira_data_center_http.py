"""Jira Data Center over HTTP with real composition and a mocked Jira transport."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from application.contracts import IngestRequest, IngestResponse
from composition import container as composition_container
from infrastructure.config import load_settings
from infrastructure.connectors.jira import data_center
from presentation.http import deps
from presentation.http.app import create_app
from test.composition.jira_fakes import dc_settings
from test.document_doubles import InMemoryDocumentCatalog
from test.doubles import InMemoryVectorStore

BASE = "/api/v1/connectors/jira"
TOKEN = "dc-e2e-personal-access-token-7f3a9b"
JIRA_URL = "https://jira.example.com/jira"


class FakeJiraServer:
    def __init__(self) -> None:
        self.reject = False
        self.fail = False
        self.seen_auth: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen_auth.add(request.headers.get("authorization", ""))
        if self.reject:
            return httpx.Response(401, text=f"bad token {TOKEN}")
        if self.fail:
            return httpx.Response(500, text=f"stack trace with {TOKEN}")
        path = request.url.path.removeprefix("/jira/rest/api/2")
        if path == "/serverInfo":
            return httpx.Response(
                200, json={"serverId": "SRV-E2E", "serverTitle": "Example Jira"}
            )
        if path == "/project":
            return httpx.Response(200, json=[{"key": "ENG", "name": "Engineering"}])
        if path == "/project/ENG":
            return httpx.Response(200, json={"key": "ENG", "name": "Engineering"})
        if path == "/search":
            return httpx.Response(
                200,
                json={
                    "startAt": 0,
                    "maxResults": 50,
                    "total": 1,
                    "issues": [
                        {
                            "id": "1",
                            "key": "ENG-1",
                            "fields": {
                                "summary": "Login",
                                "updated": "2026-09-01T10:00:00.000+0000",
                                "description": "h2. Steps\n* open",
                            },
                        }
                    ],
                },
            )
        return httpx.Response(404)


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
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = dc_settings(load_settings(), tmp_path, base_url=JIRA_URL, token=TOKEN)
    server = FakeJiraServer()
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    ingest = RecordingIngest()
    real_client = data_center.HttpJiraDataCenterClient
    monkeypatch.setattr(
        data_center,
        "HttpJiraDataCenterClient",
        lambda base_url, token: real_client(
            base_url, token, transport=httpx.MockTransport(server)
        ),
    )
    monkeypatch.setattr(deps, "get_document_catalog", lambda: catalog)
    monkeypatch.setattr(deps, "get_vector_store", lambda: store)
    monkeypatch.setattr(
        composition_container,
        "build_ingest_knowledge",
        lambda _settings, *, vector_store=None: ingest,
    )
    app = create_app()
    app.dependency_overrides[deps.get_settings] = lambda: settings
    client = TestClient(app, follow_redirects=False)
    return settings, server, catalog, ingest, client


def test_data_center_flow_never_exposes_the_token(world) -> None:
    settings, server, catalog, ingest, client = world
    responses = []

    responses.append(status := client.get(BASE))
    assert status.json()["mode"] == "data_center"
    assert status.json()["connection_state"] == "setup_required"
    responses.append(projects := client.get(f"{BASE}/projects"))
    assert projects.json()["items"] == [{"key": "ENG", "name": "Engineering"}]
    responses.append(
        selection := client.put(f"{BASE}/selection", json={"project_keys": ["ENG"]})
    )
    assert selection.json()["site"]["instance_id"] == "SRV-E2E"
    assert selection.json()["site"]["cloud_id"] is None
    responses.append(client.get(f"{BASE}/selection"))
    responses.append(sync := client.post(f"{BASE}/sync"))
    assert sync.json()["ingested_count"] == 1
    responses.append(ready := client.get(BASE))
    assert ready.json()["connection_state"] == "ready"
    assert ready.json()["document_count"] == 1
    responses.append(client.get(f"{BASE}/last-sync"))

    server.fail = True
    responses.append(failed := client.post(f"{BASE}/sync"))
    assert failed.status_code == 502
    responses.append(failed_projects := client.get(f"{BASE}/projects"))
    assert failed_projects.status_code == 502

    server.fail, server.reject = False, True
    responses.append(rejected := client.get(f"{BASE}/projects"))
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "jira_reauthorization_required"
    responses.append(after := client.get(BASE))
    assert after.json()["connection_state"] == "reauthorization_required"

    server.reject = False
    responses.append(recovered := client.get(f"{BASE}/projects"))
    assert recovered.status_code == 200
    assert client.get(BASE).json()["connection_state"] == "ready"

    assert server.seen_auth == {f"Bearer {TOKEN}"}
    for response in responses:
        assert TOKEN not in response.text
        assert TOKEN not in json.dumps(dict(response.headers))
    state_path = settings.jira_data_center.state_path
    assert TOKEN not in state_path.read_text()
    assert TOKEN not in repr(list(catalog.all()))
    assert ingest.requests
    assert TOKEN not in repr(ingest.requests)
    assert TOKEN not in repr(settings)

    removed = client.delete(BASE)
    assert removed.status_code == 204
    assert not state_path.exists()
    assert list(catalog.all()) == []
    assert settings.jira_data_center.token == TOKEN


def test_cloud_only_routes_are_409_in_data_center_mode(world) -> None:
    _settings, _server, _catalog, _ingest, client = world

    for response in (
        client.get(f"{BASE}/oauth/start"),
        client.get(f"{BASE}/oauth/callback", params={"state": "s", "code": "c"}),
        client.get(f"{BASE}/sites"),
        client.put(f"{BASE}/site", json={"cloud_id": "cloud-acme"}),
    ):
        assert response.status_code == 409
        assert response.json()["code"] == "jira_data_center_mode"


def test_unconfigured_data_center_requires_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = dc_settings(load_settings(), tmp_path, base_url=JIRA_URL, token=None)
    monkeypatch.setattr(deps, "get_document_catalog", InMemoryDocumentCatalog)
    app = create_app()
    app.dependency_overrides[deps.get_settings] = lambda: settings
    client = TestClient(app)

    status = client.get(BASE).json()
    projects = client.get(f"{BASE}/projects")

    assert status["mode"] == "data_center"
    assert status["connected"] is False
    assert status["setup_required"] is True
    assert projects.status_code == 409
    assert projects.json()["code"] == "jira_setup_required"
