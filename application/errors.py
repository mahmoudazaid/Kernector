"""Application-layer errors."""


class ApplicationValidationError(ValueError):
    """A use-case contract invariant was violated."""


class InputRejectedError(ApplicationValidationError):
    """Caller-supplied text was refused at a use-case boundary."""


class ConfigurationError(RuntimeError):
    """A required piece of environment configuration is missing or invalid.

    Subclasses `RuntimeError`, not `ValueError`: an absent credential is an
    environment failure rather than a contract violation, and
    `ApplicationValidationError` already owns the `ValueError` branch. Raised at
    the composition root, which maps an adapter's own configuration exception
    onto this type; ordinary adapter failures keep their own error type.
    """


class OllamaNotConfiguredError(ConfigurationError):
    """``OLLAMA_BASE_URL`` is absent from runtime settings."""


class InsufficientEvidenceError(RuntimeError):
    """A grounded use case found no retrieval hits above the relevance threshold.

    Expected outcome for flows such as requirements analysis where the caller
    supplied valid input but the corpus has nothing relevant enough to ground
    a model call. Presentation maps this type to a fixed user-safe sentence;
    diagnostic detail belongs on ``__cause__`` alone.
    """
