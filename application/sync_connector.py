"""Synchronize connector documents into the catalog and vector store."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from application.contracts import (
    ConnectorSyncOutcome,
    ConnectorSyncResponse,
    ConnectorSyncStatus,
    IngestRequest,
)
from application.errors import ApplicationValidationError
from application.ingest_knowledge import IngestFailure, IngestKnowledge
from application.observability import log_operation
from domain.errors import ConnectorAuthError, ConnectorError, ConnectorUnavailableError
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    ConnectorDocument,
    SourceDocument,
)
from domain.ports import DocumentCatalog, KnowledgeConnector

logger = logging.getLogger(__name__)


class SyncConnectorDocuments:
    """List remote documents, skip unchanged READY rows, and ingest the rest.

    The ingest pipeline is built lazily once per run so a skip-only sync never
    constructs embedding credentials, while a multi-document run reuses one
    ingest instance.

    Args:
        connector (KnowledgeConnector): Remote listing and fetch adapter.
        catalog (DocumentCatalog): Durable document metadata store.
        ingest_factory (Callable[[], IngestKnowledge]): Builds the shared ingest
            pipeline on first use.
        now (Callable[[], datetime] | None): Clock for catalog timestamps.
            Defaults to timezone-aware UTC now.
    """

    def __init__(
        self,
        connector: KnowledgeConnector,
        catalog: DocumentCatalog,
        ingest_factory: Callable[[], IngestKnowledge],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._connector = connector
        self._catalog = catalog
        self._ingest_factory = ingest_factory
        self._now = now or (lambda: datetime.now(UTC))
        self._shared_ingest: IngestKnowledge | None = None

    def execute(self) -> ConnectorSyncResponse:
        """Synchronize listed connector documents in listing order.

        Returns:
            ConnectorSyncResponse: Per-document outcomes in listing order.

        Raises:
            Exception: Catalog writes, ingest-pipeline construction, connection-
                wide connector failures, and unknown ingest errors abort the
                remaining documents.
        """
        documents = self._connector.list_documents()
        existing = {row.reference: row for row in self._catalog.all()}
        outcomes = [
            self._sync_one(document, existing.get(document.reference))
            for document in documents
        ]
        return ConnectorSyncResponse(outcomes=outcomes)

    def _ingest(self) -> IngestKnowledge:
        if self._shared_ingest is None:
            self._shared_ingest = self._ingest_factory()
        return self._shared_ingest

    def _sync_one(
        self,
        document: ConnectorDocument,
        previous: CatalogDocument | None,
    ) -> ConnectorSyncOutcome:
        if _is_unchanged(previous, document):
            assert previous is not None
            return ConnectorSyncOutcome(
                source_id=document.source_id,
                status=ConnectorSyncStatus.SKIPPED,
                chunk_count=previous.chunk_count,
            )
        try:
            source = self._connector.fetch_document(document)
        except (ConnectorAuthError, ConnectorUnavailableError):
            raise
        except ConnectorError as error:
            _log_document_failure(document, error)
            if previous is None:
                self._catalog.upsert(
                    _failed_row(document, uploaded_at=self._now(), error=error)
                )
            return ConnectorSyncOutcome(
                source_id=document.source_id,
                status=ConnectorSyncStatus.FAILED,
                chunk_count=0,
                error_type=type(error).__name__,
            )
        ingest = self._ingest()
        pending = _pending_row(document, source, uploaded_at=self._now())
        self._catalog.upsert(pending)
        try:
            response = ingest.execute(IngestRequest(documents=(source,)))
        except IngestFailure as error:
            self._recover_ingest_failure(previous, pending, error)
            _log_document_failure(document, error)
            return ConnectorSyncOutcome(
                source_id=document.source_id,
                status=ConnectorSyncStatus.FAILED,
                chunk_count=0,
                error_type=type(error).__name__,
            )
        except ApplicationValidationError as error:
            self._recover_pre_mutation(previous, pending, error)
            _log_document_failure(document, error)
            return ConnectorSyncOutcome(
                source_id=document.source_id,
                status=ConnectorSyncStatus.FAILED,
                chunk_count=0,
                error_type=type(error).__name__,
            )
        except Exception as error:
            self._write_status(pending, CatalogStatus.DEGRADED, error)
            _log_document_failure(document, error)
            raise
        ready = dataclasses.replace(
            pending,
            status=CatalogStatus.READY,
            chunk_count=response.chunk_count,
        )
        self._catalog.upsert(ready)
        return ConnectorSyncOutcome(
            source_id=document.source_id,
            status=ConnectorSyncStatus.INGESTED,
            chunk_count=response.chunk_count,
        )

    def _recover_ingest_failure(
        self,
        previous: CatalogDocument | None,
        pending: CatalogDocument,
        error: IngestFailure,
    ) -> None:
        if not error.vector_mutation_started:
            self._recover_pre_mutation(previous, pending, error)
            return
        self._write_status(pending, CatalogStatus.DEGRADED, error)

    def _recover_pre_mutation(
        self,
        previous: CatalogDocument | None,
        pending: CatalogDocument,
        error: BaseException,
    ) -> None:
        if previous is not None:
            self._catalog.upsert(previous)
            return
        self._write_status(pending, CatalogStatus.FAILED, error)

    def _write_status(
        self,
        pending: CatalogDocument,
        status: CatalogStatus,
        error: BaseException,
    ) -> None:
        self._catalog.upsert(
            dataclasses.replace(
                pending,
                status=status,
                error=type(error).__name__,
            )
        )


def _is_unchanged(
    existing: CatalogDocument | None, document: ConnectorDocument
) -> bool:
    return (
        existing is not None
        and existing.status is CatalogStatus.READY
        and existing.revision == document.revision
    )


def _failed_row(
    document: ConnectorDocument,
    *,
    uploaded_at: datetime,
    error: BaseException,
) -> CatalogDocument:
    return CatalogDocument(
        reference=document.reference,
        file_name=document.file_name,
        title=None,
        content_format=None,
        status=CatalogStatus.FAILED,
        uploaded_at=uploaded_at,
        chunk_count=0,
        error=type(error).__name__,
        revision=document.revision,
    )


def _pending_row(
    document: ConnectorDocument,
    source: SourceDocument,
    *,
    uploaded_at: datetime,
) -> CatalogDocument:
    return CatalogDocument(
        reference=document.reference,
        file_name=document.file_name,
        title=source.metadata.title,
        content_format=source.metadata.content_format,
        status=CatalogStatus.PENDING,
        uploaded_at=uploaded_at,
        chunk_count=0,
        error=None,
        revision=document.revision,
    )


def _log_document_failure(
    document: ConnectorDocument, error: BaseException
) -> None:
    log_operation(
        logger,
        operation="connector_sync",
        outcome="error",
        level=logging.ERROR,
        error_type=type(error).__name__,
        source_id=document.source_id,
        source_type=document.reference.source_type,
    )
