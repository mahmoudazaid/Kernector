"""Google Drive connector HTTP adapter — status and sync stubbed; no Google."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from application.contracts import (
    ConnectorSyncOutcome,
    ConnectorSyncResponse,
    ConnectorSyncStatus,
)
from composition import ConnectorSyncError, GoogleDriveStatus
from presentation.http import deps as http_deps
from presentation.http.app import create_app
from presentation.http.deps import (
    get_google_drive_status,
    get_google_drive_sync,
    get_settings,
)


def test_google_drive_status_returns_configured_and_available() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: GoogleDriveStatus(
        configured=True, available=True
    )
    client = TestClient(app)

    response = client.get("/api/v1/connectors/google-drive")

    assert response.status_code == 200
    assert response.json() == {"configured": True, "available": True}


def test_google_drive_status_returns_unconfigured() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: GoogleDriveStatus(
        configured=False, available=True
    )
    client = TestClient(app)

    response = client.get("/api/v1/connectors/google-drive")

    assert response.status_code == 200
    assert response.json() == {"configured": False, "available": True}


def test_google_drive_status_returns_extra_unavailable() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: GoogleDriveStatus(
        configured=True, available=False
    )
    client = TestClient(app)

    response = client.get("/api/v1/connectors/google-drive")

    assert response.status_code == 200
    assert response.json() == {"configured": True, "available": False}


def test_google_drive_sync_returns_ingested_skipped_failed() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: GoogleDriveStatus(
        configured=True, available=True
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


def test_openapi_includes_google_drive_paths() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    assert "/api/v1/connectors/google-drive" in schema["paths"]
    assert "/api/v1/connectors/google-drive/sync" in schema["paths"]
    props = schema["components"]["schemas"]["GoogleDriveStatusResponse"]["properties"]
    assert {"configured", "available"} <= set(props)
    assert "folder_count" not in props


def test_google_drive_sync_conflicts_when_unconfigured_without_calling_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_calls: list[str] = []
    store_builds: list[str] = []

    monkeypatch.setattr(
        http_deps,
        "sync_google_drive",
        lambda *_args, **_kwargs: sync_calls.append("sync")
        or ConnectorSyncResponse(outcomes=()),
    )
    def recording_store() -> object:
        store_builds.append("store")
        raise AssertionError("vector store must stay lazy on unconfigured POST")

    monkeypatch.setattr(http_deps, "get_vector_store", recording_store)

    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: GoogleDriveStatus(
        configured=False, available=True
    )
    app.dependency_overrides[get_settings] = lambda: SimpleNamespace()
    client = TestClient(app)

    response = client.post("/api/v1/connectors/google-drive/sync")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "google_drive_unconfigured"
    assert "not configured" in body["detail"].lower()
    assert response.headers["content-type"].startswith("application/problem+json")
    assert sync_calls == []
    assert store_builds == []


def test_google_drive_sync_maps_connector_sync_error_to_502() -> None:
    app = create_app()
    app.dependency_overrides[get_google_drive_status] = lambda: GoogleDriveStatus(
        configured=True, available=True
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
