"""Composition entry points for uploaded-document management."""

from __future__ import annotations

from pathlib import Path

import pytest

from application.errors import ConfigurationError
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


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("CHROMA_PERSIST_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION", "kernector_test")
    monkeypatch.setenv("DOCUMENT_CATALOG_PATH", str(tmp_path / "catalog" / "uploads.json"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    return load_settings()


def test_build_document_catalog_uses_settings_path(settings: Settings) -> None:
    catalog = composition_container.build_document_catalog(settings)
    assert catalog.all() == ()
    assert settings.document_catalog.path == settings.document_catalog.path


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
