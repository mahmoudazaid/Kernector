"""Composition entry points for uploaded-document management."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from application.errors import ConfigurationError, UploadTooLargeError
from application.manage_documents import (
    PartialCreateFailure,
    PartialDeleteFailure,
    UnknownDocumentError,
)
from composition import container as composition_container
from composition.errors import (
    DocumentOperationError,
    DocumentUploadError,
    PartialDocumentOperationError,
)
from domain.knowledge import (
    CatalogStatus,
    SourceReference,
    SourceType,
    UploadPayload,
)
from infrastructure.config import Settings, load_settings
from presentation.http.errors import problem_from_exception


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CHROMA_PERSIST_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION", "kernector_test")
    monkeypatch.setenv(
        "DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "catalog" / "catalog.sqlite")
    )
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "test-workspace")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    return load_settings()


def test_build_document_catalog_persists_in_sql_workspace(settings: Settings) -> None:
    from datetime import UTC, datetime

    from domain.knowledge import CatalogDocument, CatalogStatus, SourceType
    from infrastructure.catalog.sql_catalog import SqlDocumentCatalog

    catalog = composition_container.build_document_catalog(settings)
    assert type(catalog) is SqlDocumentCatalog
    document = CatalogDocument(
        reference=SourceReference("id-sql", SourceType.KNOWLEDGE_DOCUMENT),
        file_name="guide.md",
        title="Guide",
        content_format="markdown",
        status=CatalogStatus.READY,
        uploaded_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        chunk_count=1,
        error=None,
    )
    catalog.upsert(document)
    sql_path = settings.document_catalog.sql_path
    workspace_id = settings.document_catalog.workspace_id
    assert SqlDocumentCatalog(sql_path, workspace_id).get(document.reference) == document
    assert SqlDocumentCatalog(sql_path, "other-workspace").all() == ()


def test_build_document_catalog_maps_catalog_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infrastructure.catalog.errors import CatalogError

    def boom(_path: Path, _workspace_id: str) -> object:
        raise CatalogError("corrupt catalog")

    monkeypatch.setattr(composition_container, "SqlDocumentCatalog", boom)
    with pytest.raises(DocumentOperationError, match="corrupt catalog"):
        composition_container.build_document_catalog(settings)


def test_build_document_catalog_maps_oserror(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_path: Path, _workspace_id: str) -> object:
        raise OSError("read-only catalog")

    monkeypatch.setattr(composition_container, "SqlDocumentCatalog", boom)
    with pytest.raises(DocumentOperationError, match="read-only catalog"):
        composition_container.build_document_catalog(settings)


def test_build_document_catalog_requires_workspace(settings: Settings) -> None:
    missing = replace(
        settings,
        document_catalog=replace(
            settings.document_catalog,
            workspace_id=None,
        ),
    )
    with pytest.raises(ConfigurationError, match="DOCUMENT_CATALOG_WORKSPACE_ID"):
        composition_container.build_document_catalog(missing)


def test_build_document_catalog_maps_invalid_workspace_value_error(
    settings: Settings,
) -> None:
    bad = replace(
        settings,
        document_catalog=replace(
            settings.document_catalog,
            workspace_id="bad id",
        ),
    )
    with pytest.raises(ConfigurationError, match="DOCUMENT_CATALOG_WORKSPACE_ID"):
        composition_container.build_document_catalog(bad)


def test_build_document_catalog_rejects_retired_env_keys(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCUMENT_CATALOG_" + "BACKEND", "sql")
    with pytest.raises(ConfigurationError, match="DOCUMENT_CATALOG_BACKEND is retired"):
        composition_container.build_document_catalog(settings)
    monkeypatch.delenv("DOCUMENT_CATALOG_" + "BACKEND", raising=False)
    monkeypatch.setenv("DOCUMENT_CATALOG_" + "PATH", "/tmp/uploads.json")
    with pytest.raises(ConfigurationError, match="DOCUMENT_CATALOG_PATH is retired"):
        composition_container.build_document_catalog(settings)


def test_list_create_replace_delete_round_trip(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test.doubles import StubEmbeddingModel

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )

    created = composition_container.create_uploaded_document(
        settings,
        UploadPayload(file_name="guide.md", content=b"# Hello world content\n" * 20),
    )
    assert created.status is CatalogStatus.READY
    assert created.reference.source_type == SourceType.KNOWLEDGE_DOCUMENT

    listed = composition_container.list_uploaded_documents(settings)
    assert len(listed) == 1
    assert listed[0].reference == created.reference

    replaced = composition_container.replace_uploaded_document(
        settings,
        created.reference,
        UploadPayload(file_name="guide-v2.md", content=b"# Replacement text\n" * 20),
    )
    assert replaced.reference == created.reference
    assert replaced.file_name == "guide-v2.md"

    composition_container.delete_uploaded_document(settings, created.reference)
    assert composition_container.list_uploaded_documents(settings) == ()


def test_oversize_create_passes_upload_too_large_through_to_mapper(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catch-all must not re-bury UploadTooLargeError as DocumentUploadError."""
    from test.doubles import StubEmbeddingModel

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )
    tight = replace(settings, max_upload_bytes=16)
    payload = UploadPayload(file_name="big.md", content=b"x" * 17)

    with pytest.raises(UploadTooLargeError) as caught:
        composition_container.create_uploaded_document(tight, payload)

    problem = problem_from_exception(caught.value)
    body = problem.model_dump_json()
    assert problem.status == 413
    assert problem.code == "upload_too_large"
    assert "UploadPayload(" not in body
    assert "big.md" not in body
    assert not isinstance(caught.value, DocumentUploadError)


def test_oversize_replace_passes_upload_too_large_through(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test.doubles import StubEmbeddingModel

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )
    created = composition_container.create_uploaded_document(
        settings,
        UploadPayload(file_name="guide.md", content=b"# Hello world content\n" * 20),
    )
    tight = replace(settings, max_upload_bytes=16)

    with pytest.raises(UploadTooLargeError) as caught:
        composition_container.replace_uploaded_document(
            tight,
            created.reference,
            UploadPayload(file_name="big.md", content=b"x" * 17),
        )

    problem = problem_from_exception(caught.value)
    assert problem.status == 413
    assert problem.code == "upload_too_large"
    assert "big.md" not in problem.model_dump_json()


def test_replace_unknown_becomes_document_operation_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test.doubles import StubEmbeddingModel

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )
    missing = SourceReference("missing", SourceType.KNOWLEDGE_DOCUMENT)
    with pytest.raises(DocumentOperationError) as raised:
        composition_container.replace_uploaded_document(
            settings,
            missing,
            UploadPayload(file_name="x.md", content=b"# x\n"),
        )
    assert isinstance(raised.value.__cause__, UnknownDocumentError)


def test_replace_google_drive_row_is_unknown(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from domain.knowledge import CatalogDocument
    from test.doubles import StubEmbeddingModel

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )
    catalog = composition_container.build_document_catalog(settings)
    catalog.upsert(
        CatalogDocument(
            reference=SourceReference("drive-1", SourceType.GOOGLE_DRIVE),
            file_name="notes.md",
            title="notes",
            content_format="markdown",
            status=CatalogStatus.READY,
            uploaded_at=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
            chunk_count=1,
            error=None,
        )
    )
    with pytest.raises(DocumentOperationError) as raised:
        composition_container.replace_uploaded_document(
            settings,
            SourceReference("drive-1", SourceType.KNOWLEDGE_DOCUMENT),
            UploadPayload(file_name="x.md", content=b"# x\n" * 20),
        )
    assert isinstance(raised.value.__cause__, UnknownDocumentError)


def test_create_extraction_failure_becomes_document_upload_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test.doubles import StubEmbeddingModel

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )
    with pytest.raises(DocumentUploadError):
        composition_container.create_uploaded_document(
            settings,
            UploadPayload(file_name="notes.docx", content=b"x"),
        )


def test_create_dimension_mismatch_keeps_the_actionable_guidance(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The create path must not degrade to the raw vendor string."""
    from infrastructure.vectorstore.chroma import ChromaStoreError
    from test.doubles import StubEmbeddingModel

    class _MismatchedStore:
        def delete_source(self, reference: SourceReference) -> None:
            return None

        def upsert(self, embedded: object) -> None:
            raise ChromaStoreError(
                "could not write 3 record(s) to collection 'kernector_test': "
                "Collection expecting embedding with dimension of 3, got 4096"
            )

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )
    monkeypatch.setattr(
        composition_container,
        "build_vector_store",
        lambda _settings: _MismatchedStore(),
    )

    with pytest.raises(DocumentUploadError, match="embedding size") as raised:
        composition_container.create_uploaded_document(
            settings,
            UploadPayload(file_name="guide.md", content=b"# Hello world\n" * 20),
        )
    assert str(settings.chroma.persist_path) in str(raised.value)


def test_create_recovery_write_failure_maps_to_partial_operation_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both failures must survive translation as a retryable partial outcome."""
    from test.doubles import FailingEmbeddingModel

    class _RecoveryRefusingCatalog:
        def __init__(self) -> None:
            self.upserts = 0

        def all(self):
            return ()

        def get(self, reference):
            return None

        def upsert(self, document):
            self.upserts += 1
            if self.upserts > 1:
                raise RuntimeError("disk full")

        def delete(self, reference):
            return None

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: FailingEmbeddingModel(),
    )
    monkeypatch.setattr(
        composition_container,
        "build_document_catalog",
        lambda _settings: _RecoveryRefusingCatalog(),
    )

    with pytest.raises(PartialDocumentOperationError) as raised:
        composition_container.create_uploaded_document(
            settings,
            UploadPayload(file_name="guide.md", content=b"# Hello world\n" * 20),
        )
    assert isinstance(raised.value.__cause__, PartialCreateFailure)


# A credential inside a vendor error and a server path inside an adapter error:
# the two shapes of detail that must reach neither the screen nor the log file.
LEAKY_KEY = "sk-live-abc123"
LEAKY_CATALOG_PATH = "/srv/kernector/data/uploads.json"


def _partial_create_scenario(
    monkeypatch: pytest.MonkeyPatch, *, vector_mutation_started: bool
) -> tuple[Exception, Exception]:
    """Wire a create whose ingest fails and whose recovery write fails too."""
    from application.ingest_knowledge import IngestFailure

    ingest_error = IngestFailure(
        f"openrouter rejected key {LEAKY_KEY}",
        vector_mutation_started=vector_mutation_started,
        cause=RuntimeError(f"vendor said 401 for {LEAKY_KEY}"),
    )
    catalog_error = RuntimeError(f"could not write catalog at {LEAKY_CATALOG_PATH}")

    class _ExplodingIngest:
        def execute(self, request):
            raise ingest_error

    class _RecoveryRefusingCatalog:
        def __init__(self) -> None:
            self.upserts = 0

        def all(self):
            return ()

        def get(self, reference):
            return None

        def upsert(self, document):
            self.upserts += 1
            if self.upserts > 1:
                raise catalog_error

        def delete(self, reference):
            return None

    monkeypatch.setattr(
        composition_container,
        "build_ingest_knowledge",
        lambda *_a, **_k: _ExplodingIngest(),
    )
    monkeypatch.setattr(
        composition_container,
        "build_document_catalog",
        lambda _settings: _RecoveryRefusingCatalog(),
    )
    return ingest_error, catalog_error


def test_create_partial_failure_is_translated_without_internal_detail(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The translated error is UI-bound, so it carries neither original text."""
    ingest_error, catalog_error = _partial_create_scenario(
        monkeypatch, vector_mutation_started=False
    )

    with caplog.at_level("ERROR"), pytest.raises(
        PartialDocumentOperationError
    ) as raised:
        composition_container.create_uploaded_document(
            settings,
            UploadPayload(file_name="guide.md", content=b"# Hello world\n" * 20),
        )

    message = str(raised.value)
    assert message == PartialCreateFailure.MESSAGE
    assert LEAKY_KEY not in message
    assert LEAKY_CATALOG_PATH not in message
    assert str(ingest_error) not in message
    assert str(catalog_error) not in message


def test_create_partial_failure_log_holds_no_sensitive_values(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A log file outlives the request and is read by more people than the UI."""
    ingest_error, catalog_error = _partial_create_scenario(
        monkeypatch, vector_mutation_started=False
    )

    with caplog.at_level("ERROR"), pytest.raises(PartialDocumentOperationError):
        composition_container.create_uploaded_document(
            settings,
            UploadPayload(file_name="guide.md", content=b"# Hello world\n" * 20),
        )

    assert LEAKY_KEY not in caplog.text
    assert LEAKY_CATALOG_PATH not in caplog.text
    assert str(ingest_error) not in caplog.text
    assert str(catalog_error) not in caplog.text
    assert "vendor said 401" not in caplog.text
    assert "Hello world" not in caplog.text
    assert "guide.md" not in caplog.text
    # No traceback either: the chain is exactly where the detail hides.
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("mutation_started", [False, True])
def test_create_partial_failure_logs_safe_diagnostic_fields(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mutation_started: bool,
) -> None:
    """Class names and flags say which subsystem failed without quoting it."""
    _partial_create_scenario(monkeypatch, vector_mutation_started=mutation_started)

    with caplog.at_level("ERROR"), pytest.raises(PartialDocumentOperationError):
        composition_container.create_uploaded_document(
            settings,
            UploadPayload(file_name="guide.md", content=b"# Hello world\n" * 20),
        )

    records = [
        record for record in caplog.records if record.name == "composition.container"
    ]
    assert len(records) == 1
    assert records[0].getMessage() == (
        "operation=document_create outcome=partial_failure "
        "ingest_error=IngestFailure catalog_error=RuntimeError "
        f"vector_mutation_started={mutation_started}"
    )


def test_list_and_delete_need_no_embedding_credentials(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither operation embeds anything, so neither may demand an API key."""
    from test.doubles import StubEmbeddingModel

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )
    created = composition_container.create_uploaded_document(
        settings,
        UploadPayload(file_name="guide.md", content=b"# Hello world content\n" * 20),
    )

    def _no_embeddings(_settings: Settings) -> object:
        raise ConfigurationError("Missing OPENROUTER_API_KEY.")

    monkeypatch.setattr(
        composition_container, "build_embedding_model", _no_embeddings
    )

    listed = composition_container.list_uploaded_documents(settings)
    assert [row.reference for row in listed] == [created.reference]

    composition_container.delete_uploaded_document(settings, created.reference)
    assert composition_container.list_uploaded_documents(settings) == ()


def test_partial_delete_is_translated(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test.doubles import StubEmbeddingModel

    monkeypatch.setattr(
        composition_container,
        "build_embedding_model",
        lambda _settings: StubEmbeddingModel(),
    )
    created = composition_container.create_uploaded_document(
        settings,
        UploadPayload(file_name="guide.md", content=b"# Hello world content\n" * 20),
    )

    class ExplodingCatalog:
        def all(self):
            return ()

        def get(self, reference):
            return created

        def upsert(self, document):
            return None

        def delete(self, reference):
            raise RuntimeError("disk full")

    monkeypatch.setattr(
        composition_container,
        "build_document_catalog",
        lambda _settings: ExplodingCatalog(),
    )
    with pytest.raises(PartialDocumentOperationError) as raised:
        composition_container.delete_uploaded_document(settings, created.reference)
    assert isinstance(raised.value.__cause__, PartialDeleteFailure)
