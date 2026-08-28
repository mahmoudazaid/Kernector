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
