"""Application-layer errors."""


class ApplicationValidationError(ValueError):
    """A use-case contract invariant was violated."""


class InputRejectedError(ApplicationValidationError):
    """Caller-supplied input was refused at a use-case boundary.

    The message must be display-safe copy, not diagnostic text: presentation
    maps this type to a client-facing 4xx and may render ``str(error)``
    verbatim.
    """


class UploadTooLargeError(InputRejectedError):
    """An upload exceeded the configured byte limit.

    The message is composed by the class from integers, so no caller string
    can reach it and presentation may render it directly. Pass
    ``actual_bytes`` only when it is a true file size; omit it for
    whole-request pre-checks (e.g. Content-Length including multipart framing).
    """

    def __init__(self, *, limit_bytes: int, actual_bytes: int | None = None) -> None:
        if actual_bytes is None:
            message = f"Upload must be at most {limit_bytes} bytes."
        else:
            message = (
                f"Upload must be at most {limit_bytes} bytes; "
                f"this file is {actual_bytes} bytes."
            )
        super().__init__(message)
        self.limit_bytes = limit_bytes
        self.actual_bytes = actual_bytes


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
