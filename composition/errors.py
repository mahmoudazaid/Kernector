"""Composition-facing errors translated from infrastructure adapters."""


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


class DocumentOperationError(RuntimeError):
    """Uploaded-document list/create/replace/delete failed after translation.

    Wraps application management failures (unknown document, partial delete,
    degraded replace recovery) so presentation stays free of infrastructure
    exception types while still seeing honest, retryable outcomes.

    Plain instances mean nothing was mutated: the operation stopped before it
    touched the catalog or the vector store, so there is nothing to reconcile.
    """


class PartialDocumentOperationError(DocumentOperationError):
    """The operation stopped midway and left catalog/vector state to reconcile.

    Separate from its base so presentation can tell the user to retry only when
    a retry is actually needed. Telling someone a catalog row is stranded after
    a failure that never opened the store sends them looking for damage that
    does not exist.
    """


class RequirementsEvidenceUnavailableError(RuntimeError):
    """Requirements analysis found nothing above the relevance threshold.

    Translated at the composition edge from the pack's ``MissingEvidenceError``
    so presentation can say "your corpus has nothing relevant" without
    importing a pack exception type — and so that outcome does not arrive
    disguised as a generic operational failure.
    """
