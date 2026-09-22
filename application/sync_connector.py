"""Synchronize connector documents into the catalog and vector store."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Sequence
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
    SourceReference,
)
from domain.ports import DocumentCatalog, KnowledgeConnector, VectorStore

logger = logging.getLogger(__name__)


class SyncConnectorDocuments:
    """List remote documents, skip unchanged READY rows, and ingest the rest.

    The ingest pipeline is built lazily once per run so a skip-only sync never
    constructs embedding credentials, while a multi-document run reuses one
    ingest instance.

    When ``reconcile_missing`` is enabled, catalog rows whose ``source_type`` is
    in ``reconcile_source_types`` and whose reference was not listed are hard-
    deleted (vectors first, then the catalog row) after a clean run. Incomplete
    listings must raise from the connector so reconcile never runs on a short
    list. Deletion is further narrowed by ``reconcile_connector_ids`` and/or
    ``reconcile_source_id_prefixes`` so a source type alone never deletes
    across connector instances. When ``reconcile_connector_ids`` is set,
    catalog rows with ``connector_id is None`` are treated as legacy
    pre-identity rows and claimed into that reconcile scope.

    If the run has any ``FAILED`` outcomes, same-scope rows are left alone
    (ingest failures must not look like remote deletes). Rows whose source-id
    scope (for example ``owner/repo:``) is outside every listed document are
    still removed so a repository change cannot leave the previous repo's
    documents behind.

    Args:
        connector (KnowledgeConnector): Remote listing and fetch adapter.
        catalog (DocumentCatalog): Durable document metadata store.
        ingest_factory (Callable[[], IngestKnowledge]): Builds the shared ingest
            pipeline on first use.
        now (Callable[[], datetime] | None): Clock for catalog timestamps.
            Defaults to timezone-aware UTC now.
        reconcile_missing (bool): When True, delete in-scope catalog rows that
            were not listed. Defaults to False (Drive semantics).
        reconcile_source_types (frozenset[str]): Source types eligible for
            reconcile. Empty by default; required non-empty when reconcile is on.
        reconcile_source_id_prefixes (frozenset[str]): When non-empty, only
            rows whose ``source_id`` starts with one of these prefixes are
            eligible for reconcile (narrower than source type alone).
        reconcile_connector_ids (frozenset[str]): When non-empty, only rows
            whose ``connector_id`` is in this set are eligible for reconcile.
        vector_store_factory (Callable[[], VectorStore] | None): Lazy vector
            store getter used only for reconcile deletes. Required when
            ``reconcile_missing`` is True.
    """

    def __init__(
        self,
        connector: KnowledgeConnector,
        catalog: DocumentCatalog,
        ingest_factory: Callable[[], IngestKnowledge],
        now: Callable[[], datetime] | None = None,
        *,
        reconcile_missing: bool = False,
        reconcile_source_types: frozenset[str] = frozenset(),
        reconcile_source_id_prefixes: frozenset[str] = frozenset(),
        reconcile_connector_ids: frozenset[str] = frozenset(),
        vector_store_factory: Callable[[], VectorStore] | None = None,
    ) -> None:
        if reconcile_missing and vector_store_factory is None:
            raise ApplicationValidationError(
                "vector_store_factory is required when reconcile_missing is True"
            )
        if reconcile_missing and not reconcile_source_types:
            raise ApplicationValidationError(
                "reconcile_source_types must be non-empty when reconcile_missing is True"
            )
        if reconcile_missing and not (
            reconcile_source_id_prefixes or reconcile_connector_ids
        ):
            raise ApplicationValidationError(
                "reconcile_connector_ids or reconcile_source_id_prefixes must be "
                "non-empty when reconcile_missing is True"
            )
        self._connector = connector
        self._catalog = catalog
        self._ingest_factory = ingest_factory
        self._now = now or (lambda: datetime.now(UTC))
        self._shared_ingest: IngestKnowledge | None = None
        self._reconcile_missing = reconcile_missing
        self._reconcile_source_types = reconcile_source_types
        self._reconcile_source_id_prefixes = reconcile_source_id_prefixes
        self._reconcile_connector_ids = reconcile_connector_ids
        self._vector_store_factory = vector_store_factory

    def execute(self) -> ConnectorSyncResponse:
        """Synchronize listed connector documents in listing order.

        Returns:
            ConnectorSyncResponse: Per-document outcomes in listing order,
            followed by optional removals sorted by ``source_id``.

        Raises:
            Exception: Catalog writes, ingest-pipeline construction, connection-
                wide connector failures, unknown ingest errors, and reconcile
                adapter failures abort the remaining work.
        """
        documents = self._connector.list_documents()
        existing = {row.reference: row for row in self._catalog.all()}
        outcomes = [
            self._sync_one(document, existing.get(document.reference))
            for document in documents
        ]
        removals = self._reconcile(documents, existing, outcomes)
        return ConnectorSyncResponse(outcomes=(*outcomes, *removals))

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
            stamped = _connector_id_of(document)
            if stamped and previous.connector_id != stamped:
                self._catalog.upsert(
                    dataclasses.replace(previous, connector_id=stamped)
                )
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
                now = self._now()
                self._catalog.upsert(
                    _failed_row(
                        document,
                        created_at=now,
                        updated_at=now,
                        error=error,
                    )
                )
            return ConnectorSyncOutcome(
                source_id=document.source_id,
                status=ConnectorSyncStatus.FAILED,
                chunk_count=0,
                error_type=type(error).__name__,
            )
        ingest = self._ingest()
        updated_at = self._now()
        created_at = previous.created_at if previous is not None else updated_at
        source = dataclasses.replace(
            source,
            metadata=dataclasses.replace(
                source.metadata,
                created_at=created_at,
                updated_at=updated_at,
            ),
        )
        pending = _pending_row(
            document,
            source,
            created_at=created_at,
            updated_at=updated_at,
        )
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
        status = (
            ConnectorSyncStatus.UPDATED
            if previous is not None and previous.status is CatalogStatus.READY
            else ConnectorSyncStatus.INGESTED
        )
        return ConnectorSyncOutcome(
            source_id=document.source_id,
            status=status,
            chunk_count=response.chunk_count,
        )

    def _reconcile(
        self,
        documents: Sequence[ConnectorDocument],
        existing: dict[SourceReference, CatalogDocument],
        outcomes: Sequence[ConnectorSyncOutcome],
    ) -> tuple[ConnectorSyncOutcome, ...]:
        if not self._reconcile_missing:
            return ()
        has_failures = any(
            outcome.status is ConnectorSyncStatus.FAILED for outcome in outcomes
        )
        if has_failures and not documents:
            return ()
        listed = {document.reference for document in documents}
        listed_scopes = {
            scope
            for document in documents
            if (scope := _source_id_scope(document.source_id)) is not None
        }
        prefixes = self._reconcile_source_id_prefixes
        connector_ids = self._reconcile_connector_ids
        missing = sorted(
            (
                row
                for reference, row in existing.items()
                if reference.source_type in self._reconcile_source_types
                and reference not in listed
                and (
                    not prefixes
                    or any(
                        reference.source_id.startswith(prefix)
                        for prefix in prefixes
                    )
                )
                and _row_in_connector_scope(row, connector_ids)
                and (
                    not has_failures
                    or _source_id_scope(reference.source_id) not in listed_scopes
                )
            ),
            key=lambda row: row.reference.source_id,
        )
        if not missing:
            return ()
        assert self._vector_store_factory is not None
        store = self._vector_store_factory()
        removals: list[ConnectorSyncOutcome] = []
        for row in missing:
            store.delete_source(row.reference)
            self._catalog.delete(row.reference)
            removals.append(
                ConnectorSyncOutcome(
                    source_id=row.reference.source_id,
                    status=ConnectorSyncStatus.REMOVED,
                    chunk_count=0,
                )
            )
        return tuple(removals)

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


def _connector_id_of(document: ConnectorDocument) -> str | None:
    value = document.extra.get("connector_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _row_in_connector_scope(
    row: CatalogDocument, connector_ids: frozenset[str]
) -> bool:
    """Return whether ``row`` is eligible for connector-scoped reconcile.

    Rows with a matching ``connector_id`` are always in scope. Rows with
    ``connector_id is None`` are treated as legacy pre-identity catalog
    entries and claimed by the active connector reconcile so a repository
    change can still remove them.
    """
    if not connector_ids:
        return True
    if row.connector_id is None:
        return True
    return row.connector_id in connector_ids


def _source_id_scope(source_id: str) -> str | None:
    """Return the stable scope prefix for a connector source id.

    GitHub repo files use ``owner/repo:path``; Project issues use ``issue:…``.
    Scope is the segment through the first ``:`` so a repository change can
    drop the previous repo even when the current sync has ingest failures.
    """
    if not source_id or ":" not in source_id:
        return None
    return source_id.split(":", 1)[0] + ":"


def _failed_row(
    document: ConnectorDocument,
    *,
    created_at: datetime,
    updated_at: datetime,
    error: BaseException,
) -> CatalogDocument:
    return CatalogDocument(
        reference=document.reference,
        file_name=document.file_name,
        title=None,
        content_format=None,
        status=CatalogStatus.FAILED,
        created_at=created_at,
        updated_at=updated_at,
        chunk_count=0,
        error=type(error).__name__,
        revision=document.revision,
        connector_id=_connector_id_of(document),
    )


def _pending_row(
    document: ConnectorDocument,
    source: SourceDocument,
    *,
    created_at: datetime,
    updated_at: datetime,
) -> CatalogDocument:
    return CatalogDocument(
        reference=document.reference,
        file_name=document.file_name,
        title=source.metadata.title,
        content_format=source.metadata.content_format,
        status=CatalogStatus.PENDING,
        created_at=created_at,
        updated_at=updated_at,
        chunk_count=0,
        error=None,
        revision=document.revision,
        connector_id=_connector_id_of(document),
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
