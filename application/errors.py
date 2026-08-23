"""Application-layer errors."""


class ApplicationValidationError(ValueError):
    """A use-case contract invariant was violated."""
