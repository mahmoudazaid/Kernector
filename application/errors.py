"""Application-layer errors."""


class ApplicationValidationError(ValueError):
    """A use-case contract invariant was violated."""


class ConfigurationError(RuntimeError):
    """A required piece of environment configuration is missing or invalid.

    Subclasses `RuntimeError`, not `ValueError`: an absent credential is an
    environment failure rather than a contract violation, and
    `ApplicationValidationError` already owns the `ValueError` branch. Raised at
    the composition root, which maps an adapter's own configuration exception
    onto this type; ordinary adapter failures keep their own error type.
    """
