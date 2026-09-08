"""Google OAuth state/connection stores — no live Google calls."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.error import URLError

import pytest

from infrastructure.config import GoogleOAuthSettings
from infrastructure.connectors import google_oauth as oauth_mod
from infrastructure.connectors.google_oauth import (
    GoogleOAuthConnection,
    GoogleOAuthConnectionStore,
    GoogleOAuthError,
    GoogleOAuthStateStore,
    HttpGoogleOAuthGateway,
    authorization_url,
)


def _connection(**overrides: object) -> GoogleOAuthConnection:
    values = dict(
        refresh_token="1//refresh-secret",
        access_token="ya29.access-secret",
        account_email="ada@example.com",
        folder_count=1,
        last_synced_at=None,
        last_sync_new=None,
        last_sync_updated=None,
        last_sync_unchanged=None,
        last_sync_failed=None,
        reauthorization_required=False,
    )
    values.update(overrides)
    return GoogleOAuthConnection(**values)  # type: ignore[arg-type]


def test_state_is_single_use_and_rejects_replay(tmp_path: Path) -> None:
    store = GoogleOAuthStateStore(tmp_path / "state.json", ttl_seconds=600)
    token = store.issue()

    assert store.consume(token) is True
    assert store.consume(token) is False
    assert store.consume(None) is False
    assert store.consume("unknown") is False


def test_state_file_is_owner_readable_only(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = GoogleOAuthStateStore(path, ttl_seconds=600)
    store.issue()

    assert path.stat().st_mode & 0o777 == 0o600


def test_connection_repr_redacts_tokens() -> None:
    connection = _connection()
    text = repr(connection)

    assert "1//refresh-secret" not in text
    assert "ya29.access-secret" not in text
    assert "***" in text
    assert "ada@example.com" in text


def test_connection_store_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "conn.json"
    store = GoogleOAuthConnectionStore(path)
    store.save(_connection())

    loaded = store.load()
    assert loaded is not None
    assert loaded.account_email == "ada@example.com"
    assert loaded.refresh_token == "1//refresh-secret"
    assert path.stat().st_mode & 0o777 == 0o600

    store.clear()
    assert store.load() is None


def test_authorization_url_uses_exact_redirect_and_readonly_scope() -> None:
    settings = GoogleOAuthSettings(
        client_id="client.apps.googleusercontent.com",
        client_secret="client-secret",
        redirect_uri="http://127.0.0.1:8000/api/v1/connectors/google-drive/oauth/callback",
    )
    url = authorization_url(settings, state="csrf-state")

    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client-secret" not in url
    assert "drive.readonly" in url
    assert "access_type=offline" in url
    assert "state=csrf-state" in url
    assert (
        "redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Fapi%2Fv1%2Fconnectors"
        "%2Fgoogle-drive%2Foauth%2Fcallback"
        in url
    )


def test_exchange_logs_omit_tokens(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_args: object, **_kwargs: object) -> object:
        raise URLError("timed out")

    monkeypatch.setattr(oauth_mod, "urlopen", boom)
    gateway = HttpGoogleOAuthGateway(
        GoogleOAuthSettings(
            client_id="client",
            client_secret="client-secret",
            redirect_uri="http://127.0.0.1:8000/callback",
        )
    )
    caplog.set_level(logging.INFO, logger="infrastructure.connectors.google_oauth")

    with pytest.raises(GoogleOAuthError):
        gateway.exchange_code("4/secret-auth-code")

    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert "client-secret" not in combined
    assert "4/secret-auth-code" not in combined
    assert "invalid_grant" not in combined
