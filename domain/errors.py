"""Domain errors."""


class DomainValidationError(ValueError):
    """A domain invariant was violated."""


class ProviderError(RuntimeError):
    """An LLM, embedding, or query-rewrite provider call failed at runtime.

    Adapters raise this with a fixed, adapter-authored message. Vendor detail
    belongs on ``__cause__`` only — never in the exception text — so
    presentation can render ``str(error)`` without leaking provider bodies.
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


class ToolFailureError(RuntimeError):
    """A tool port invocation failed.

    Reserved until a tool adapter exists; ``Tool.run`` documents this type so
    callers have one known failure to catch.
    """
