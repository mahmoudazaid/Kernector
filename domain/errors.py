"""Domain errors."""


class DomainValidationError(ValueError):
    """A domain invariant was violated."""


class ConfigurationBoundaryError(RuntimeError):
    """Missing or invalid environment configuration at a composition boundary.

    Marker base so infrastructure adapters can let typed config failures pass
    through without importing ``application.errors``. Application
    ``ConfigurationError`` (and subclasses) inherit this type.

    Do not raise this marker directly from adapters — raise a concrete
    application ``ConfigurationError`` subclass (or let composition map an
    infrastructure config error onto one) so presentation can classify it.
    """


class ProviderError(RuntimeError):
    """An LLM, embedding, or query-rewrite provider call failed at runtime.

    Exception text is diagnostic only. Vendor detail belongs on ``__cause__``
    alone — never in the exception text. Presentation must always map
    ``ProviderError`` to a fixed user-safe message; it must not render
    ``str(error)``.
    """


class QueryRewriterError(ProviderError):
    """The query rewriter failed to produce a usable retrieval query.

    Provider-neutral: adapters raise this from ``rewrite()`` when invocation
    fails or the model returns blank content after normalization. Application
    code catches this single type rather than every ``RuntimeError``.
    """


class VectorStoreError(RuntimeError):
    """A vector-store adapter failed on a read or write operation.

    Empty search results are not this error — they are a normal empty sequence.
    """


class ToolArgumentValidationError(DomainValidationError):
    """Tool arguments were rejected before execution began.

    Callers should treat this as validation, not as an operational tool failure.
    """


class ToolFailureError(RuntimeError):
    """A tool port invocation failed after valid arguments were accepted.

    ``Tool.run`` documents this type so callers have one known operational
    failure to catch, distinct from ``ToolArgumentValidationError``.
    """


class ConnectorError(RuntimeError):
    """A connector adapter failed without exposing provider details."""


class ConnectorAuthError(ConnectorError):
    """Credentials or permissions were rejected."""


class ConnectorUnavailableError(ConnectorError):
    """The provider is temporarily unreachable or throttling requests."""
