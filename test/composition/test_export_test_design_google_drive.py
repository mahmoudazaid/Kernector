"""Facade/HTTP coverage for Test Design → Google Drive export."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from application.contracts import InvokeToolRequest, InvokeToolResponse
from application.errors import (
    GoogleDriveNotConnectedError,
    GoogleDriveReauthorizationRequiredError,
)
from composition.test_design import TestDesignFacade
from composition.test_design_errors import TestDesignValidationError
from domain.errors import ConnectorAuthError, ToolFailureError
from domain.knowledge import SourceReference, SourceType
from infrastructure.config import DomainToolSettings, GoogleOAuthSettings, load_settings
from infrastructure.connectors.google_drive.oauth import (
    DRIVE_FILE_SCOPE,
    DRIVE_READ_SCOPE,
    GoogleOAuthConnection,
    GoogleOAuthConnectionStore,
)
from packs.software_delivery.test_design.models import TestCandidate, TestCoverageDraft
from presentation.http.app import create_app
from presentation.http.deps import get_test_design_facade


class _FakeInvoke:
    def __init__(
        self, *, result: str | None = None, error: BaseException | None = None
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[InvokeToolRequest] = []

    def execute(self, request: InvokeToolRequest) -> InvokeToolResponse:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return InvokeToolResponse(request.tool_name, self.result)


def _settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_CLIENT_ID", "client.apps.googleusercontent.com"
    )
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "http://127.0.0.1:8000/api/v1/connectors/google-drive/oauth/callback",
    )
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_PATH", str(tmp_path / "conn.json"))
    monkeypatch.setenv("GOOGLE_OAUTH_STATE_PATH", str(tmp_path / "state.json"))
    loaded = load_settings()
    return replace(
        loaded,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
        google_oauth=GoogleOAuthSettings(
            client_id="client.apps.googleusercontent.com",
            client_secret="client-secret",
            redirect_uri=(
                "http://127.0.0.1:8000/api/v1/connectors/google-drive/oauth/callback"
            ),
            frontend_redirect="http://localhost:3000/documents",
            token_path=tmp_path / "conn.json",
            state_path=tmp_path / "state.json",
            state_ttl_seconds=600,
        ),
    )


def _facade(settings, tmp_path: Path) -> TestDesignFacade:
    return TestDesignFacade(
        settings=settings,
        store_path=tmp_path / "workspace.sqlite",
        workspace_id="default",
        oauth_preflight=lambda: "token",
        live_source_reader_factory=lambda _token: None,  # type: ignore[arg-type, return-value]
    )


def _seed_draft(facade: TestDesignFacade, *, selected: bool = True) -> str:
    draft_id = "draft-export-1"
    draft = TestCoverageDraft(
        draft_id=draft_id,
        workspace_id="default",
        conversation_id="conv-1",
        source_reference=SourceReference("issue:1", SourceType.GITHUB),
        ticket_identifier="owner/repo#1",
        status="coverage_review",
        candidates=(
            TestCandidate(
                candidate_id="cand-1",
                title="Valid login",
                category="positive",
                rationale="AC",
                evidence_references=(
                    SourceReference("issue:1", SourceType.GITHUB),
                ),
                selected=selected,
                origin="suggested",
            ),
        ),
        version=1,
    )
    facade._repository().create(draft)
    return draft_id


def _save_connection(
    settings,
    *,
    granted_scopes: frozenset[str] | None = None,
) -> GoogleOAuthConnectionStore:
    tokens = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    scopes = granted_scopes if granted_scopes is not None else frozenset(
        {DRIVE_READ_SCOPE, DRIVE_FILE_SCOPE}
    )
    tokens.save(
        GoogleOAuthConnection(
            refresh_token="1//refresh-secret",
            access_token="ya29.access-secret",
            account_email="ada@example.com",
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_failed=None,
            reauthorization_required=False,
            granted_scopes=scopes,
        )
    )
    return tokens


def test_export_happy_path_returns_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    tokens = _save_connection(settings)
    facade = _facade(settings, tmp_path)
    draft_id = _seed_draft(facade)
    invoke = _FakeInvoke(
        result='{"file_id":"drive-99","file_name":"owner-repo-1.md"}'
    )
    monkeypatch.setattr(
        "composition.container.build_invoke_tool",
        lambda *_a, **_k: invoke,
    )

    receipt = facade.export_to_google_drive(draft_id, folder_id="folderExport123")

    assert receipt.file_id == "drive-99"
    assert receipt.file_name == "owner-repo-1.md"
    assert tokens.load().reauthorization_required is False
    assert invoke.calls[0].arguments["folder_id"] == "folderExport123"
    assert "ya29" not in repr(receipt)
    assert "1//refresh" not in repr(receipt)


def test_export_missing_drive_file_scope_does_not_mutate_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    tokens = _save_connection(
        settings, granted_scopes=frozenset({DRIVE_READ_SCOPE})
    )
    facade = _facade(settings, tmp_path)
    draft_id = _seed_draft(facade)
    invoke = _FakeInvoke(result='{"file_id":"x","file_name":"y.md"}')
    monkeypatch.setattr(
        "composition.container.build_invoke_tool",
        lambda *_a, **_k: invoke,
    )

    with pytest.raises(GoogleDriveReauthorizationRequiredError):
        facade.export_to_google_drive(draft_id, folder_id="folderExport123")

    assert tokens.load().reauthorization_required is False
    assert invoke.calls == []


def test_export_not_connected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    facade = _facade(settings, tmp_path)
    draft_id = _seed_draft(facade)

    with pytest.raises(GoogleDriveNotConnectedError):
        facade.export_to_google_drive(draft_id, folder_id="folderExport123")


def test_export_marks_reauth_on_genuine_connector_auth_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    tokens = _save_connection(settings)
    facade = _facade(settings, tmp_path)
    draft_id = _seed_draft(facade)
    invoke = _FakeInvoke(error=ConnectorAuthError("token ya29.secret rejected"))
    monkeypatch.setattr(
        "composition.container.build_invoke_tool",
        lambda *_a, **_k: invoke,
    )

    with pytest.raises(GoogleDriveReauthorizationRequiredError):
        facade.export_to_google_drive(draft_id, folder_id="folderExport123")

    assert tokens.load().reauthorization_required is True


def test_export_malformed_receipt_is_tool_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    _save_connection(settings)
    facade = _facade(settings, tmp_path)
    draft_id = _seed_draft(facade)
    invoke = _FakeInvoke(result='{"file_id":"","file_name":"x.md"}')
    monkeypatch.setattr(
        "composition.container.build_invoke_tool",
        lambda *_a, **_k: invoke,
    )

    with pytest.raises(ToolFailureError, match="export failed"):
        facade.export_to_google_drive(draft_id, folder_id="folderExport123")


def test_export_rejects_invalid_folder_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    facade = _facade(settings, tmp_path)
    draft_id = _seed_draft(facade)

    with pytest.raises(TestDesignValidationError):
        facade.export_to_google_drive(draft_id, folder_id="not a valid id!")


def test_export_rejects_empty_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    facade = _facade(settings, tmp_path)
    draft_id = _seed_draft(facade, selected=False)

    with pytest.raises(TestDesignValidationError, match="select at least one"):
        facade.export_to_google_drive(draft_id, folder_id="folderExport123")


def test_http_export_maps_not_connected_to_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    facade = _facade(settings, tmp_path)
    draft_id = _seed_draft(facade)
    app = create_app(cors_origins=())
    app.dependency_overrides[get_test_design_facade] = lambda: facade
    client = TestClient(app)

    response = client.post(
        f"/api/v1/test-design/drafts/{draft_id}/export/google-drive",
        json={"folder_id": "folderExport123"},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "google_drive_not_connected"
    assert "ya29" not in body["detail"]
    assert "1//refresh" not in str(body)


def test_http_export_maps_missing_scope_to_409_without_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    tokens = _save_connection(
        settings, granted_scopes=frozenset({DRIVE_READ_SCOPE})
    )
    facade = _facade(settings, tmp_path)
    draft_id = _seed_draft(facade)
    app = create_app(cors_origins=())
    app.dependency_overrides[get_test_design_facade] = lambda: facade
    client = TestClient(app)

    response = client.post(
        f"/api/v1/test-design/drafts/{draft_id}/export/google-drive",
        json={"folder_id": "folderExport123"},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "google_drive_reauthorization_required"
    assert tokens.load().reauthorization_required is False
    assert "ya29" not in body["detail"]


def test_http_export_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    _save_connection(settings)
    facade = _facade(settings, tmp_path)
    draft_id = _seed_draft(facade)
    invoke = _FakeInvoke(
        result='{"file_id":"drive-99","file_name":"owner-repo-1.md"}'
    )
    monkeypatch.setattr(
        "composition.container.build_invoke_tool",
        lambda *_a, **_k: invoke,
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_test_design_facade] = lambda: facade
    client = TestClient(app)

    response = client.post(
        f"/api/v1/test-design/drafts/{draft_id}/export/google-drive",
        json={"folder_id": "folderExport123"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "file_id": "drive-99",
        "file_name": "owner-repo-1.md",
    }


def test_http_export_invalid_folder_id_returns_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    facade = _facade(settings, tmp_path)
    draft_id = _seed_draft(facade)
    app = create_app(cors_origins=())
    app.dependency_overrides[get_test_design_facade] = lambda: facade
    client = TestClient(app)

    response = client.post(
        f"/api/v1/test-design/drafts/{draft_id}/export/google-drive",
        json={"folder_id": "not a valid id!"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
