"""Google Drive connector HTTP adapter — OAuth and status stubbed; no Google."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from application.contracts import (
    ConnectorSyncOutcome,
    ConnectorSyncResponse,
    ConnectorSyncStatus,
)
from application.errors import ConfigurationError, GoogleDriveNotConnectedError
from infrastructure.catalog.errors import CatalogError
from presentation.http.schemas import GOOGLE_DRIVE_SELECTION_LIST_MAX
from composition import (
    ConnectorSyncError,
    GoogleDriveBrowsePage,
    GoogleDriveLastSync,
    GoogleDriveSelection,
    GoogleDriveSelectedItem,
    GoogleDriveStatus,
)
from presentation.http import deps as http_deps
from presentation.http.app import create_app
from presentation.http.deps import (
    get_google_drive_disconnect,
    get_google_drive_oauth_callback,
    get_google_drive_oauth_start,
    get_google_drive_selection_read,
    get_google_drive_selection_write,
    get_google_drive_browse,
    get_google_drive_status,
    get_google_drive_sync,
    get_settings,
)

_SECRET_KEYS = (
    "refresh_token",
    "access_token",
    "client_secret",
    "authorization_code",
)


def _status(**overrides: object) -> GoogleDriveStatus:
    values = dict(
        configured=False,
        available=True,
        connected=False,
        oauth_ready=False,
        account_email=None,
        document_count=0,
        folder_count=None,
        last_sync=None,
        reauthorization_required=False,
        setup_required=False,
        connection_state="disconnected",
        sync_scope=None,
    )
    values.update(overrides)
    return GoogleDriveStatus(**values)  # type: ignore[arg-type]


def _status_json(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "configured": False,
        "available": True,
        "connected": False,
        "oauth_ready": False,
        "account_email": None,
        "document_count": 0,
        "folder_count": None,
        "last_sync": None,
        "reauthorization_required": False,
        "setup_required": False,
        "connection_state": "disconnected",
        "sync_scope": None,
    }
    payload.update(overrides)
    return payload


def test_status_dep_passes_the_process_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = object()
    seen: list[object] = []

    monkeypatch.setattr(http_deps, "get_document_catalog", lambda: catalog)

    def fake_status(_settings, *, catalog=None, catalog_unavailable=False):
        seen.append((catalog, catalog_unavailable))
        return _status()

    monkeypatch.setattr(http_deps, "google_drive_status", fake_status)
    http_deps.get_google_drive_status(SimpleNamespace())
    assert seen == [(catalog, False)]


@pytest.mark.parametrize(
    "error",
    [
        OSError("catalog directory missing"),
        CatalogError("catalog migration failed"),
        ConfigurationError("DOCUMENT_CATALOG_WORKSPACE_ID is required"),
    ],
    ids=["oserror", "catalog_error", "configuration_error"],
)
def test_status_dep_degrades_when_catalog_construction_fails(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    seen: list[object] = []

    def boom() -> object:
        raise error

    monkeypatch.setattr(http_deps, "get_document_catalog", boom)

    def fake_status(_settings, *, catalog=None, catalog_unavailable=False):
        seen.append((catalog, catalog_unavailable))
        return _status()

    monkeypatch.setattr(http_deps, "google_drive_status", fake_status)
    http_deps.get_google_drive_status(SimpleNamespace())
    assert seen == [(None, True)]


def test_sync_dep_passes_the_process_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    monkeypatch.setattr(http_deps, "get_document_catalog", lambda: object())

    def fake_sync(_settings, *, catalog=None, catalog_factory=None, vector_store_factory=None):
        seen.append(catalog_factory)
        return ConnectorSyncResponse(outcomes=())

    monkeypatch.setattr(http_deps, "sync_google_drive_oauth", fake_sync)
    http_deps.get_google_drive_sync(SimpleNamespace())()
    assert seen == [http_deps.get_document_catalog]


def test_google_drive_status_returns_presentation_fields() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: _status(
        configured=True, available=True
    )
    client = TestClient(app)

    response = client.get("/api/v1/connectors/google-drive")

    assert response.status_code == 200
    assert response.json() == _status_json(configured=True, available=True)
    body = response.json()
    for key in _SECRET_KEYS:
        assert key not in body


def test_google_drive_status_returns_connected_metadata() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: _status(
        connected=True,
        oauth_ready=True,
        account_email="ada@example.com",
        document_count=4,
        folder_count=1,
        last_sync=GoogleDriveLastSync(
            synced_at="2026-09-08T12:00:00+00:00",
            new_count=1,
            updated_count=2,
            unchanged_count=3,
            failed_count=0,
        ),
        setup_required=False,
        connection_state="ready",
        sync_scope="1 folder",
    )
    client = TestClient(app)

    response = client.get("/api/v1/connectors/google-drive")

    assert response.status_code == 200
    assert response.json() == _status_json(
        connected=True,
        oauth_ready=True,
        account_email="ada@example.com",
        document_count=4,
        folder_count=1,
        last_sync={
            "synced_at": "2026-09-08T12:00:00+00:00",
            "new_count": 1,
            "updated_count": 2,
            "unchanged_count": 3,
            "failed_count": 0,
        },
        setup_required=False,
        connection_state="ready",
        sync_scope="1 folder",
    )


def test_google_drive_status_returns_unconfigured() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: _status()
    client = TestClient(app)

    response = client.get("/api/v1/connectors/google-drive")

    assert response.status_code == 200
    assert response.json() == _status_json()


def test_google_drive_status_returns_extra_unavailable() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: _status(
        configured=True, available=False
    )
    client = TestClient(app)

    response = client.get("/api/v1/connectors/google-drive")

    assert response.status_code == 200
    assert response.json() == _status_json(configured=True, available=False)


def test_google_drive_sync_returns_ingested_skipped_failed() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: _status(
        connected=True, oauth_ready=True
    )
    app.dependency_overrides[get_google_drive_sync] = lambda: (
        lambda: ConnectorSyncResponse(
            outcomes=(
                ConnectorSyncOutcome(
                    source_id="drive:file-1",
                    status=ConnectorSyncStatus.INGESTED,
                    chunk_count=3,
                ),
                ConnectorSyncOutcome(
                    source_id="drive:file-2",
                    status=ConnectorSyncStatus.SKIPPED,
                    chunk_count=1,
                ),
                ConnectorSyncOutcome(
                    source_id="drive:file-3",
                    status=ConnectorSyncStatus.SKIPPED,
                    chunk_count=2,
                ),
            )
        )
    )
    client = TestClient(app)

    response = client.post("/api/v1/connectors/google-drive/sync")

    assert response.status_code == 200
    assert response.json() == {
        "ingested_count": 1,
        "skipped_count": 2,
        "failed_count": 0,
        "outcomes": [
            {
                "source_id": "drive:file-1",
                "status": "ingested",
                "chunk_count": 3,
                "error_type": None,
            },
            {
                "source_id": "drive:file-2",
                "status": "skipped",
                "chunk_count": 1,
                "error_type": None,
            },
            {
                "source_id": "drive:file-3",
                "status": "skipped",
                "chunk_count": 2,
                "error_type": None,
            },
        ],
    }


def test_openapi_includes_google_drive_oauth_paths() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/v1/connectors/google-drive" in paths
    assert "/api/v1/connectors/google-drive/sync" in paths
    assert "/api/v1/connectors/google-drive/oauth/start" in paths
    assert "/api/v1/connectors/google-drive/oauth/callback" in paths
    assert "/api/v1/connectors/google-drive/items" in paths
    assert "/api/v1/connectors/google-drive/selection" in paths
    assert "delete" in paths["/api/v1/connectors/google-drive"]
    assert "put" in paths["/api/v1/connectors/google-drive/selection"]
    props = schema["components"]["schemas"]["GoogleDriveStatusResponse"]["properties"]
    assert {
        "configured",
        "available",
        "connected",
        "oauth_ready",
        "account_email",
        "document_count",
        "folder_count",
        "last_sync",
        "reauthorization_required",
        "setup_required",
        "connection_state",
        "sync_scope",
    } <= set(props)
    for key in _SECRET_KEYS:
        assert key not in props
        assert key not in schema["components"]["schemas"]


def test_google_drive_sync_conflicts_when_disconnected_without_calling_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_builds: list[str] = []

    monkeypatch.setattr(
        http_deps,
        "sync_google_drive_oauth",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            GoogleDriveNotConnectedError("Google Drive is not connected")
        ),
    )

    def recording_store() -> object:
        store_builds.append("store")
        raise AssertionError("vector store must stay lazy on disconnected POST")

    monkeypatch.setattr(http_deps, "get_vector_store", recording_store)

    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: _status(
        configured=True, available=True, connected=False
    )
    app.dependency_overrides[get_settings] = lambda: SimpleNamespace()
    client = TestClient(app)

    response = client.post("/api/v1/connectors/google-drive/sync")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "google_drive_not_connected"
    assert "not connected" in body["detail"].lower()
    assert response.headers["content-type"].startswith("application/problem+json")
    assert store_builds == []
    for key in _SECRET_KEYS:
        assert key not in body["detail"]


def test_google_drive_sync_maps_connector_sync_error_to_502() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: _status(
        connected=True
    )

    def failing_sync() -> ConnectorSyncResponse:
        raise ConnectorSyncError("vendor body /secret/sa.json")

    app.dependency_overrides[get_google_drive_sync] = lambda: failing_sync
    client = TestClient(app)

    response = client.post("/api/v1/connectors/google-drive/sync")

    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "connector_sync_failed"
    assert body["detail"] == "The Google Drive connector sync failed."
    assert "/secret/sa.json" not in body["detail"]
    assert response.headers["content-type"].startswith("application/problem+json")


def test_oauth_start_redirects_to_google_without_secrets() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_oauth_start] = lambda: (
        lambda: (
            "https://accounts.google.com/o/oauth2/v2/auth"
            "?client_id=public-client"
            "&redirect_uri=http://127.0.0.1:8000/callback"
            "&state=csrf-state-1"
            "&scope=https://www.googleapis.com/auth/drive.readonly"
        )
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/connectors/google-drive/oauth/start",
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    assert parsed.netloc == "accounts.google.com"
    query = parse_qs(parsed.query)
    assert query["state"] == ["csrf-state-1"]
    for secret in ("super-secret", "ya29.", "1//"):
        assert secret not in location


def test_oauth_start_unconfigured_redirects_to_hub_not_json() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_oauth_start] = lambda: (
        lambda: "http://localhost:3000/documents?drive=unconfigured"
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/connectors/google-drive/oauth/start",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == (
        "http://localhost:3000/documents?drive=unconfigured"
    )
    assert "application/json" not in response.headers.get("content-type", "")
    assert "problem+json" not in response.headers.get("content-type", "")


def test_oauth_callback_success_redirects_to_hub() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_oauth_callback] = lambda: (
        lambda _state, _code, _error: "http://localhost:3000/documents?drive=connected"
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/connectors/google-drive/oauth/callback"
        "?state=csrf&code=4/secret-auth-code",
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    assert location == "http://localhost:3000/documents?drive=connected"
    assert "secret-auth-code" not in location
    assert "code=" not in location


def test_oauth_callback_denied_redirects_with_denied() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_oauth_callback] = lambda: (
        lambda _state, _code, error: (
            "http://localhost:3000/documents?drive=denied"
            if error == "access_denied"
            else "http://localhost:3000/documents?drive=error"
        )
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/connectors/google-drive/oauth/callback?error=access_denied",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].endswith("drive=denied")


def test_oauth_callback_invalid_state_redirects() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_oauth_callback] = lambda: (
        lambda _state, _code, _error: "http://localhost:3000/documents?drive=invalid_state"
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/connectors/google-drive/oauth/callback?state=replayed",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "drive=invalid_state" in response.headers["location"]


def test_disconnect_returns_204() -> None:
    called: list[str] = []
    app = create_app()
    app.dependency_overrides[get_google_drive_disconnect] = lambda: (
        lambda: called.append("disconnect")
    )
    client = TestClient(app)

    response = client.delete("/api/v1/connectors/google-drive")

    assert response.status_code == 204
    assert response.content == b""
    assert called == ["disconnect"]


def test_sync_runs_when_connected_without_selection() -> None:
    sync_calls: list[str] = []
    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: _status(
        connected=True,
        oauth_ready=True,
        setup_required=False,
        connection_state="ready",
        sync_scope=None,
    )
    app.dependency_overrides[get_google_drive_sync] = lambda: (
        lambda: sync_calls.append("sync") or ConnectorSyncResponse(outcomes=())
    )
    client = TestClient(app)

    response = client.post("/api/v1/connectors/google-drive/sync")

    assert response.status_code == 200
    assert sync_calls == ["sync"]


def test_items_return_presentation_rows_without_tokens() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_browse] = lambda: (
        lambda **_kwargs: SimpleNamespace(
            items=(
                SimpleNamespace(
                    id="folder-1",
                    name="Specs",
                    kind="folder",
                    mime_type="application/vnd.google-apps.folder",
                    supported=True,
                    modified_at="2026-09-08T12:00:00.000Z",
                ),
            ),
            next_page_token="page-2",
        )
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/connectors/google-drive/items?parent_id=root&kind=folders"
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "items": [
            {
                "id": "folder-1",
                "name": "Specs",
                "kind": "folder",
                "mime_type": "application/vnd.google-apps.folder",
                "supported": True,
                "modified_at": "2026-09-08T12:00:00.000Z",
            }
        ],
        "next_page_token": "page-2",
    }
    for key in _SECRET_KEYS:
        assert key not in body
        assert key not in str(body)


def test_get_selection_returns_saved_ids_not_names_as_identity() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_selection_read] = lambda: (
        lambda: GoogleDriveSelection(
            folders=(GoogleDriveSelectedItem(id="folder-1", name="Specs"),),
            files=(GoogleDriveSelectedItem(id="file-9", name="guide.md"),),
        )
    )
    client = TestClient(app)

    response = client.get("/api/v1/connectors/google-drive/selection")

    assert response.status_code == 200
    assert response.json() == {
        "folders": [{"id": "folder-1", "name": "Specs"}],
        "files": [{"id": "file-9", "name": "guide.md"}],
    }


def test_put_selection_replaces_by_id() -> None:
    saved: list[object] = []
    app = create_app()
    app.dependency_overrides[get_google_drive_selection_write] = lambda: (
        lambda **kwargs: saved.append(kwargs)
        or GoogleDriveSelection(
            folders=kwargs["folders"],
            files=kwargs["files"],
        )
    )
    client = TestClient(app)

    response = client.put(
        "/api/v1/connectors/google-drive/selection",
        json={
            "folders": [{"id": "folder-1", "name": "Specs"}],
            "files": [],
        },
    )

    assert response.status_code == 200
    assert saved[0]["folders"][0].id == "folder-1"
    assert response.json()["folders"][0]["id"] == "folder-1"


def test_put_selection_rejects_root_id() -> None:
    saved: list[object] = []
    app = create_app()
    app.dependency_overrides[get_google_drive_selection_write] = lambda: (
        lambda **kwargs: saved.append(kwargs)
        or GoogleDriveSelection(
            folders=kwargs["folders"],
            files=kwargs["files"],
        )
    )
    client = TestClient(app)

    response = client.put(
        "/api/v1/connectors/google-drive/selection",
        json={"folders": [{"id": "root", "name": "My Drive"}], "files": []},
    )

    assert response.status_code == 422
    assert saved == []


def test_put_selection_rejects_long_item_name() -> None:
    saved: list[object] = []
    app = create_app()
    app.dependency_overrides[get_google_drive_selection_write] = lambda: (
        lambda **kwargs: saved.append(kwargs)
        or GoogleDriveSelection(
            folders=kwargs["folders"],
            files=kwargs["files"],
        )
    )
    client = TestClient(app)

    response = client.put(
        "/api/v1/connectors/google-drive/selection",
        json={"folders": [{"id": "folder-1", "name": "n" * 257}], "files": []},
    )

    assert response.status_code == 422
    assert saved == []


def test_get_selection_loads_more_than_put_bound() -> None:
    folders = tuple(
        GoogleDriveSelectedItem(id=f"folder-{index}", name=f"Folder {index}")
        for index in range(GOOGLE_DRIVE_SELECTION_LIST_MAX + 10)
    )
    app = create_app()
    app.dependency_overrides[get_google_drive_selection_read] = lambda: (
        lambda: GoogleDriveSelection(folders=folders, files=())
    )
    client = TestClient(app)

    response = client.get("/api/v1/connectors/google-drive/selection")

    assert response.status_code == 200
    assert len(response.json()["folders"]) == GOOGLE_DRIVE_SELECTION_LIST_MAX + 10


def test_get_selection_accepts_long_drive_names() -> None:
    folders = (
        GoogleDriveSelectedItem(id="folder-1", name="n" * 3000),
    )
    app = create_app()
    app.dependency_overrides[get_google_drive_selection_read] = lambda: (
        lambda: GoogleDriveSelection(folders=folders, files=())
    )
    client = TestClient(app)

    response = client.get("/api/v1/connectors/google-drive/selection")

    assert response.status_code == 200
    assert response.json()["folders"][0]["name"] == "n" * 3000
