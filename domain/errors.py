"""Domain errors."""


class DomainValidationError(ValueError):
    """A domain invariant was violated."""


class QueryRewriterError(RuntimeError):
    """The query rewriter failed to produce a usable retrieval query.

    Provider-neutral: adapters raise this from ``rewrite()`` when invocation
    fails or the model returns blank content after normalization. Application
    code catches this single type rather than every ``RuntimeError``.
    """
