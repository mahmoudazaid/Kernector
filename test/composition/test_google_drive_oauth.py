"""User OAuth composition — mocked Google gateway; no live credentials."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from application.contracts import (
    ConnectorSyncOutcome,
    ConnectorSyncResponse,
    ConnectorSyncStatus,
)
from application.errors import (
    GoogleDriveNotConnectedError,
    GoogleDriveSelectionRequiredError,
)
from composition import (
    browse_google_drive_items,
    complete_google_drive_oauth,
    delete_uploaded_document,
    disconnect_google_drive_oauth,
    get_google_drive_selection,
    google_drive_status,
    put_google_drive_selection,
    start_google_drive_oauth,
    sync_google_drive_oauth,
)
from composition import container as composition_container
from composition.container import GoogleDriveSelectedItem
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceReference,
    SourceType,
)
from infrastructure.config import GoogleOAuthSettings, load_settings
from infrastructure.connectors.google_oauth import (
    GoogleDriveSelectedItem as StoredItem,
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
    stored = tokens.load()
    assert stored is not None
    assert stored.folders == ()
    assert stored.files == ()
    assert stored.folder_count == 0
    status = google_drive_status(settings)
    assert status.connected is True
    assert status.setup_required is False
    assert status.connection_state == "ready"
    assert status.sync_scope is None


def test_callback_reconnect_keeps_saved_scope(settings) -> None:
    states = GoogleOAuthStateStore(settings.google_oauth.state_path, ttl_seconds=600)
    tokens = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    tokens.save(
        GoogleOAuthConnection(
            refresh_token="1//old-refresh",
            access_token=None,
            account_email="ada@example.com",
            folder_count=1,
            last_synced_at="2026-09-08T12:00:00+00:00",
            last_sync_new=1,
            last_sync_updated=0,
            last_sync_unchanged=2,
            last_sync_failed=0,
            reauthorization_required=True,
            folders=(StoredItem(id="folder-1", name="Specs"),),
            files=(),
        )
    )
    state = states.issue()
    url = complete_google_drive_oauth(
        settings,
        state=state,
        code="4/auth-code",
        error=None,
        state_store=states,
        connection_store=tokens,
        gateway=FakeGateway(),
    )

    assert url.endswith("drive=connected")
    stored = tokens.load()
    assert stored is not None
    assert stored.refresh_token == "1//refresh-secret"
    assert stored.reauthorization_required is False
    assert stored.folders == (StoredItem(id="folder-1", name="Specs"),)
    assert stored.last_synced_at == "2026-09-08T12:00:00+00:00"
    assert stored.last_sync_unchanged == 2


class OtherAccountGateway(FakeGateway):
    def fetch_account_email(self, _access_token: str) -> str | None:
        return "other@example.com"


def test_callback_reconnect_as_other_account_resets_scope(settings) -> None:
    states = GoogleOAuthStateStore(settings.google_oauth.state_path, ttl_seconds=600)
    tokens = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    tokens.save(
        GoogleOAuthConnection(
            refresh_token="1//old-refresh",
            access_token=None,
            account_email="ada@example.com",
            folder_count=1,
            last_synced_at="2026-09-08T12:00:00+00:00",
            last_sync_new=1,
            last_sync_updated=0,
            last_sync_unchanged=2,
            last_sync_failed=0,
            reauthorization_required=True,
            folders=(StoredItem(id="folder-1", name="Specs"),),
            files=(),
        )
    )
    state = states.issue()
    url = complete_google_drive_oauth(
        settings,
        state=state,
        code="4/auth-code",
        error=None,
        state_store=states,
        connection_store=tokens,
        gateway=OtherAccountGateway(),
    )

    assert url.endswith("drive=connected")
    stored = tokens.load()
    assert stored is not None
    assert stored.account_email == "other@example.com"
    assert stored.folders == ()
    assert stored.last_synced_at is None
    assert stored.folder_count == 0


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


def test_status_counts_ready_drive_documents_only(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = InMemoryDocumentCatalog()
    uploaded_at = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    catalog.upsert(
        CatalogDocument(
            reference=SourceReference("file-ready", SourceType.GOOGLE_DRIVE),
            file_name="ready.md",
            title="ready",
            content_format="markdown",
            status=CatalogStatus.READY,
            uploaded_at=uploaded_at,
            chunk_count=1,
            error=None,
            revision="1",
        )
    )
    catalog.upsert(
        CatalogDocument(
            reference=SourceReference("file-failed", SourceType.GOOGLE_DRIVE),
            file_name="failed.md",
            title=None,
            content_format=None,
            status=CatalogStatus.FAILED,
            uploaded_at=uploaded_at,
            chunk_count=0,
            error="ConnectorError",
            revision="1",
        )
    )
    catalog.upsert(
        CatalogDocument(
            reference=SourceReference("upload-1", SourceType.KNOWLEDGE_DOCUMENT),
            file_name="spec.md",
            title="Spec",
            content_format="markdown",
            status=CatalogStatus.READY,
            uploaded_at=uploaded_at,
            chunk_count=3,
            error=None,
        )
    )
    monkeypatch.setattr(
        composition_container, "build_document_catalog", lambda _settings: catalog
    )
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

    assert google_drive_status(settings).document_count == 1


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
            folders=(StoredItem(id="folder-1", name="Specs"),),
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


def test_sync_without_selection_conflicts(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    tokens.save(
        GoogleOAuthConnection(
            refresh_token="1//refresh-secret",
            access_token=None,
            account_email="ada@example.com",
            folder_count=0,
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

    with pytest.raises(GoogleDriveSelectionRequiredError):
        sync_google_drive_oauth(
            settings,
            catalog=InMemoryDocumentCatalog(),
            vector_store=object(),  # type: ignore[arg-type]
            connection_store=tokens,
        )

    stored = tokens.load()
    assert stored is not None
    assert stored.last_synced_at is None


def test_oauth_sync_does_not_revert_selection_changed_during_run(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    tokens.save(
        GoogleOAuthConnection(
            refresh_token="1//refresh-secret",
            access_token=None,
            account_email="ada@example.com",
            folder_count=1,
            folders=(StoredItem(id="folder-1", name="Specs"),),
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

    def _sync(*_args, **_kwargs):
        tokens.save(
            replace(
                tokens.load(),
                folders=(StoredItem(id="folder-2", name="New"),),
                folder_count=1,
            )
        )
        return ConnectorSyncResponse(outcomes=())

    monkeypatch.setattr(composition_container, "sync_google_drive", _sync)

    sync_google_drive_oauth(
        settings,
        catalog=InMemoryDocumentCatalog(),
        vector_store=object(),  # type: ignore[arg-type]
        connection_store=tokens,
    )

    stored = tokens.load()
    assert stored is not None
    assert stored.folders == (StoredItem(id="folder-2", name="New"),)
    assert stored.last_synced_at is not None


def test_oauth_sync_does_not_recreate_grant_cleared_during_run(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    tokens.save(
        GoogleOAuthConnection(
            refresh_token="1//refresh-secret",
            access_token=None,
            account_email="ada@example.com",
            folder_count=1,
            folders=(StoredItem(id="folder-1", name="Specs"),),
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

    def _sync(*_args, **_kwargs):
        tokens.clear()
        return ConnectorSyncResponse(outcomes=())

    monkeypatch.setattr(composition_container, "sync_google_drive", _sync)

    sync_google_drive_oauth(
        settings,
        catalog=InMemoryDocumentCatalog(),
        vector_store=object(),  # type: ignore[arg-type]
        connection_store=tokens,
    )

    assert tokens.load() is None


def test_oauth_sync_uses_vector_store_factory_only_after_guards(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    tokens.save(
        GoogleOAuthConnection(
            refresh_token="1//refresh-secret",
            access_token=None,
            account_email="ada@example.com",
            folder_count=0,
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )
    built: list[str] = []

    def _factory():
        built.append("store")
        raise AssertionError("vector store must stay lazy until selection exists")

    with pytest.raises(GoogleDriveSelectionRequiredError):
        sync_google_drive_oauth(
            settings,
            catalog=InMemoryDocumentCatalog(),
            vector_store_factory=_factory,
            connection_store=tokens,
        )

    assert built == []


def test_oauth_sync_passes_factory_store_into_sync(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    tokens.save(
        GoogleOAuthConnection(
            refresh_token="1//refresh-secret",
            access_token=None,
            account_email="ada@example.com",
            folder_count=1,
            folders=(StoredItem(id="folder-1", name="Specs"),),
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )
    store = object()
    captured: list[object] = []
    monkeypatch.setattr(
        composition_container,
        "build_google_drive_oauth_connector",
        lambda *_args, **_kwargs: object(),
    )

    def _sync(*_args, **kwargs):
        captured.append(kwargs.get("vector_store"))
        return ConnectorSyncResponse(outcomes=())

    monkeypatch.setattr(composition_container, "sync_google_drive", _sync)

    sync_google_drive_oauth(
        settings,
        catalog=InMemoryDocumentCatalog(),
        vector_store_factory=lambda: store,
        connection_store=tokens,
    )

    assert captured == [store]


class FakeBrowseFiles:
    def __init__(self) -> None:
        self.list_calls: list[dict[str, object]] = []
        self.get_calls: list[str] = []

    def list(self, **kwargs: object) -> object:
        self.list_calls.append(dict(kwargs))

        class Request:
            def execute(self) -> dict[str, object]:
                return {
                    "files": [
                        {
                            "id": "folder-1",
                            "name": "Specs",
                            "mimeType": "application/vnd.google-apps.folder",
                            "modifiedTime": "2026-09-08T12:00:00.000Z",
                        }
                    ]
                }

        return Request()

    def get(self, **kwargs: object) -> object:
        file_id = str(kwargs.get("fileId") or "")
        self.get_calls.append(file_id)

        class Request:
            def execute(self) -> dict[str, object]:
                return {
                    "id": file_id,
                    "name": "Specs",
                    "mimeType": "application/vnd.google-apps.folder",
                    "trashed": False,
                }

        return Request()


def test_browse_and_put_selection_use_ids_and_skip_tokens(settings) -> None:
    tokens = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    tokens.save(
        GoogleOAuthConnection(
            refresh_token="1//refresh-secret",
            access_token="ya29.access-secret",
            account_email="ada@example.com",
            folder_count=0,
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )
    files = FakeBrowseFiles()
    page = browse_google_drive_items(
        settings,
        kind="folders",
        connection_store=tokens,
        files=files,
    )
    assert [item.id for item in page.items] == ["folder-1"]
    assert "ya29.access-secret" not in repr(page)
    assert "1//refresh-secret" not in repr(page)

    saved = put_google_drive_selection(
        settings,
        folders=(GoogleDriveSelectedItem(id="folder-1", name="Old name"),),
        files=(),
        connection_store=tokens,
        files_resource=files,
    )
    assert saved.folders[0].id == "folder-1"
    assert saved.folders[0].name == "Specs"
    loaded = get_google_drive_selection(settings, connection_store=tokens)
    assert loaded.folders[0].id == "folder-1"
    status = google_drive_status(settings)
    assert status.setup_required is False
    assert status.connection_state == "ready"
    assert status.sync_scope == "1 folder"


def test_put_selection_allows_empty(settings) -> None:
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
            folders=(StoredItem(id="folder-1", name="Specs"),),
        )
    )
    saved = put_google_drive_selection(
        settings, folders=(), files=(), connection_store=tokens
    )
    assert saved.folders == ()
    assert saved.files == ()
    loaded = get_google_drive_selection(settings, connection_store=tokens)
    assert loaded.folders == ()
    assert loaded.files == ()
    status = google_drive_status(settings)
    assert status.setup_required is False
    assert status.connection_state == "ready"


def test_delete_drive_document_drops_file_from_selection(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test.doubles import InMemoryVectorStore

    catalog = InMemoryDocumentCatalog()
    drive_ref = SourceReference("file-9", SourceType.GOOGLE_DRIVE)
    catalog.upsert(
        CatalogDocument(
            reference=drive_ref,
            file_name="guide.md",
            title="guide",
            content_format="markdown",
            status=CatalogStatus.READY,
            uploaded_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
            chunk_count=1,
            error=None,
            revision="1",
        )
    )
    monkeypatch.setattr(
        composition_container, "build_document_catalog", lambda _settings: catalog
    )
    monkeypatch.setattr(
        composition_container,
        "build_vector_store",
        lambda _settings: InMemoryVectorStore(),
    )
    tokens = GoogleOAuthConnectionStore(settings.google_oauth.token_path)
    tokens.save(
        GoogleOAuthConnection(
            refresh_token="1//refresh-secret",
            access_token=None,
            account_email="ada@example.com",
            folder_count=0,
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_failed=None,
            reauthorization_required=False,
            files=(
                StoredItem(id="file-9", name="guide.md"),
                StoredItem(id="keep", name="keep.md"),
            ),
        )
    )

    delete_uploaded_document(
        settings,
        SourceReference("file-9", SourceType.KNOWLEDGE_DOCUMENT),
    )

    assert catalog.get(drive_ref) is None
    loaded = tokens.load()
    assert loaded is not None
    assert [item.id for item in loaded.files] == ["keep"]
