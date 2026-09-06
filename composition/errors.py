"""Composition-facing errors translated from infrastructure adapters."""

from __future__ import annotations

from typing import Literal

DocumentPartialOperation = Literal["create", "replace", "delete"]


class KnowledgeLoadError(RuntimeError):
    """The configured knowledge input could not be loaded."""


class DocumentUploadError(RuntimeError):
    """An uploaded document could not be extracted or stored for ingestion.

    Wraps domain, extraction, and vector-store failures so presentation never
    imports infrastructure exception types. Subclassing ``RuntimeError`` (like
    ``KnowledgeLoadError``) means the original ``ValueError``-ness of a
    ``DomainValidationError`` is discarded; presentation catches this type by
    name, so nothing depends on the discarded base.
    """


class DocumentContentError(DocumentUploadError):
    """The uploaded file has no extractable text layer.

    Distinct from other extraction failures so HTTP can return 422 instead of
    a generic operational 500 — the caller supplied a file that cannot be
    ingested as written, not a transient store or provider fault.
    """


class DocumentOperationError(RuntimeError):
    """Uploaded-document list/create/replace/delete failed after translation.

    Wraps application management failures (unknown document, partial delete,
    degraded replace recovery) so presentation stays free of infrastructure
    exception types while still seeing honest, retryable outcomes.

    Plain instances mean nothing was mutated: the operation stopped before it
    touched the catalog or the vector store, so there is nothing to reconcile.
    """


class UnknownUploadedDocumentError(DocumentOperationError):
    """Replace targeted a source ID that is not in the uploaded-document catalog."""


class PartialDocumentOperationError(DocumentOperationError):
    """The operation stopped midway and left catalog/vector state to reconcile.

    Separate from its base so presentation can tell the user to retry only when
    a retry is actually needed. Telling someone a catalog row is stranded after
    a failure that never opened the store sends them looking for damage that
    does not exist.
    """

    def __init__(
        self,
        message: str = "",
        *,
        operation: DocumentPartialOperation,
    ) -> None:
        super().__init__(message)
        self.operation = operation
