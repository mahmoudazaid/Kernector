"""User OAuth composition — mocked Google gateway; no live credentials."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from application.contracts import (
    ConnectorSyncOutcome,
    ConnectorSyncResponse,
    ConnectorSyncStatus,
)
from application.errors import GoogleDriveNotConnectedError
from composition import (
    complete_google_drive_oauth,
    disconnect_google_drive_oauth,
    google_drive_status,
    start_google_drive_oauth,
    sync_google_drive_oauth,
)
from composition import container as composition_container
from infrastructure.config import GoogleOAuthSettings, load_settings
from infrastructure.connectors.google_oauth import (
    GoogleOAuthConnection,
    GoogleOAuthConnectionStore,
    GoogleOAuthGrant,
    GoogleOAuthStateStore,
)
from test.document_doubles import InMemoryDocumentCatalog


class FakeGateway:
    def __init__(self) -> None:
        self.exchanged: list[str] = []
        self.revoked: list[str] = []

    def exchange_code(self, code: str) -> GoogleOAuthGrant:
        self.exchanged.append(code)
        return GoogleOAuthGrant(
            access_token="ya29.access-secret",
            refresh_token="1//refresh-secret",
        )

    def fetch_account_email(self, _access_token: str) -> str | None:
        return "ada@example.com"

    def revoke(self, token: str) -> None:
        self.revoked.append(token)


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_REDIRECT_URI", raising=False)
    loaded = load_settings()
    return replace(
        loaded,
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


def test_start_without_oauth_client_returns_hub_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_REDIRECT_URI", raising=False)
    url = start_google_drive_oauth(load_settings())
    assert url.endswith("drive=unconfigured")
    assert "accounts.google.com" not in url


def test_start_issues_state_and_returns_google_url(settings) -> None:
    store = GoogleOAuthStateStore(settings.google_oauth.state_path, ttl_seconds=600)
    url = start_google_drive_oauth(settings, state_store=store)

    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client-secret" not in url
    assert store.consume  # store has an issued token
    raw = settings.google_oauth.state_path.read_text(encoding="utf-8")
    assert "client-secret" not in raw


def test_callback_denied_does_not_persist(settings) -> None:
    store = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    url = complete_google_drive_oauth(
        settings,
        state=None,
        code=None,
        error="access_denied",
        connection_store=store,
        gateway=FakeGateway(),
    )

    assert url == "http://localhost:3000/documents?drive=denied"
    assert store.load() is None


def test_callback_rejects_replayed_state(settings) -> None:
    states = GoogleOAuthStateStore(settings.google_oauth.state_path, ttl_seconds=600)
    tokens = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    gateway = FakeGateway()
    state = states.issue()

    first = complete_google_drive_oauth(
        settings,
        state=state,
        code="4/auth-code",
        error=None,
        state_store=states,
        connection_store=tokens,
        gateway=gateway,
    )
    second = complete_google_drive_oauth(
        settings,
        state=state,
        code="4/auth-code",
        error=None,
        state_store=states,
        connection_store=tokens,
        gateway=gateway,
    )

    assert first.endswith("drive=connected")
    assert second.endswith("drive=invalid_state")
    assert gateway.exchanged == ["4/auth-code"]
    assert "4/auth-code" not in first
    assert "1//refresh-secret" not in first


def test_status_reads_store_not_memory(settings) -> None:
    assert google_drive_status(settings).connected is False
    GoogleOAuthConnectionStore(settings.google_oauth.token_path).save(
        GoogleOAuthConnection(
            refresh_token="1//refresh-secret",
            access_token=None,
            account_email="ada@example.com",
            folder_count=1,
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )

    status = google_drive_status(settings)
    assert status.connected is True
    assert status.account_email == "ada@example.com"
    assert status.last_sync is None


def test_disconnect_revokes_and_clears(settings) -> None:
    tokens = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    tokens.save(
        GoogleOAuthConnection(
            refresh_token="1//refresh-secret",
            access_token=None,
            account_email="ada@example.com",
            folder_count=1,
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )
    gateway = FakeGateway()

    disconnect_google_drive_oauth(
        settings, connection_store=tokens, gateway=gateway
    )

    assert gateway.revoked == ["1//refresh-secret"]
    assert tokens.load() is None
    with pytest.raises(GoogleDriveNotConnectedError):
        disconnect_google_drive_oauth(
            settings, connection_store=tokens, gateway=gateway
        )


def test_oauth_sync_persists_last_sync_counts(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    tokens.save(
        GoogleOAuthConnection(
            refresh_token="1//refresh-secret",
            access_token=None,
            account_email="ada@example.com",
            folder_count=1,
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )
    monkeypatch.setattr(
        composition_container,
        "build_google_drive_oauth_connector",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        composition_container,
        "sync_google_drive",
        lambda *_args, **_kwargs: ConnectorSyncResponse(
            outcomes=(
                ConnectorSyncOutcome(
                    source_id="drive:new",
                    status=ConnectorSyncStatus.INGESTED,
                    chunk_count=1,
                ),
                ConnectorSyncOutcome(
                    source_id="drive:skip",
                    status=ConnectorSyncStatus.SKIPPED,
                    chunk_count=1,
                ),
            )
        ),
    )

    result = sync_google_drive_oauth(
        settings,
        catalog=InMemoryDocumentCatalog(),
        vector_store=object(),  # type: ignore[arg-type]
        connection_store=tokens,
    )

    stored = tokens.load()
    assert stored is not None
    assert stored.last_sync_new == 1
    assert stored.last_sync_updated == 0
    assert stored.last_sync_unchanged == 1
    assert stored.last_sync_failed == 0
    assert stored.last_synced_at is not None
    assert result.ingested_count == 1
