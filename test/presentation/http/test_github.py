"""GitHub connector HTTP adapter — OAuth and status stubbed; no GitHub network."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from application.contracts import (
    ConnectorSyncOutcome,
    ConnectorSyncResponse,
    ConnectorSyncStatus,
)
from composition import GitHubLastSync, GitHubStatus
from presentation.http.app import create_app
from presentation.http.deps import (
    get_github_disconnect,
    get_github_oauth_callback,
    get_github_oauth_start,
    get_github_status,
    get_github_sync,
)


def _status(**overrides: object) -> GitHubStatus:
    values = dict(
        configured=False,
        available=True,
        connected=False,
        oauth_ready=False,
        account_login=None,
        document_count=0,
        owner=None,
        repo=None,
        project_owner=None,
        project_number=None,
        last_sync=None,
        reauthorization_required=False,
        connection_state="disconnected",
        sync_scope=None,
    )
    values.update(overrides)
    return GitHubStatus(**values)  # type: ignore[arg-type]


def test_status_returns_presentation_safe_payload() -> None:
    app = create_app()
    app.dependency_overrides[get_github_status] = lambda: _status(
        configured=True,
        oauth_ready=True,
        connected=True,
        account_login="octocat",
        owner="acme",
        repo="docs",
        document_count=2,
        connection_state="connected",
        last_sync=GitHubLastSync(
            synced_at="2026-09-13T12:00:00+00:00",
            new_count=1,
            updated_count=0,
            unchanged_count=1,
            removed_count=0,
            failed_count=0,
        ),
    )
    client = TestClient(app)
    response = client.get("/api/v1/connectors/github")
    assert response.status_code == 200
    body = response.json()
    assert body["account_login"] == "octocat"
    assert body["owner"] == "acme"
    assert body["repo"] == "docs"
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "token" not in body


def test_sync_projects_updated_and_removed_counts() -> None:
    app = create_app()
    app.dependency_overrides[get_github_status] = lambda: _status(connected=True)
    app.dependency_overrides[get_github_sync] = lambda: (
        lambda: ConnectorSyncResponse(
            outcomes=(
                ConnectorSyncOutcome("a", ConnectorSyncStatus.INGESTED, 2),
                ConnectorSyncOutcome("b", ConnectorSyncStatus.UPDATED, 3),
                ConnectorSyncOutcome("c", ConnectorSyncStatus.REMOVED, 0),
            )
        )
    )
    client = TestClient(app)
    response = client.post("/api/v1/connectors/github/sync")
    assert response.status_code == 200
    assert response.json() == {
        "ingested_count": 1,
        "updated_count": 1,
        "skipped_count": 0,
        "failed_count": 0,
        "removed_count": 1,
        "outcomes": [
            {
                "source_id": "a",
                "status": "ingested",
                "chunk_count": 2,
                "error_type": None,
            },
            {
                "source_id": "b",
                "status": "updated",
                "chunk_count": 3,
                "error_type": None,
            },
            {
                "source_id": "c",
                "status": "removed",
                "chunk_count": 0,
                "error_type": None,
            },
        ],
    }


def test_oauth_start_redirects() -> None:
    app = create_app()
    app.dependency_overrides[get_github_oauth_start] = (
        lambda: (lambda: "https://github.com/login/oauth/authorize?state=abc")
    )
    client = TestClient(app, follow_redirects=False)
    response = client.get("/api/v1/connectors/github/oauth/start")
    assert response.status_code == 302
    assert response.headers["location"].startswith(
        "https://github.com/login/oauth/authorize"
    )


def test_oauth_callback_redirects_to_hub() -> None:
    app = create_app()
    app.dependency_overrides[get_github_oauth_callback] = (
        lambda: (
            lambda state, code, error: "http://localhost:3000/documents?github=connected"
        )
    )
    client = TestClient(app, follow_redirects=False)
    response = client.get(
        "/api/v1/connectors/github/oauth/callback",
        params={"state": "s", "code": "c"},
    )
    assert response.status_code == 302
    assert "github=connected" in response.headers["location"]


def test_disconnect_returns_204() -> None:
    called = {"n": 0}

    def _disconnect() -> None:
        called["n"] += 1

    app = create_app()
    app.dependency_overrides[get_github_disconnect] = lambda: _disconnect
    client = TestClient(app)
    response = client.delete("/api/v1/connectors/github")
    assert response.status_code == 204
    assert called["n"] == 1
