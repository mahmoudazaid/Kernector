"""Application-layer errors."""


class ApplicationValidationError(ValueError):
    """A use-case contract invariant was violated."""


class ObservationIntegrityError(ApplicationValidationError):
    """Same-run RAG observation invariants were violated.

    Raised by ``ObservedRagRunner`` when retrieve/generation hit sharing cannot
    be confirmed. Distinct from ``InputRejectedError`` so live Judge composition
    can hard-fail only integrity breaches.
    """


class InputRejectedError(ApplicationValidationError):
    """Caller-supplied input was refused at a use-case boundary.

    The message must be display-safe copy, not diagnostic text: presentation
    maps this type to a client-facing 4xx and may render ``str(error)``
    verbatim.
    """


class UploadTooLargeError(InputRejectedError):
    """An upload exceeded the configured byte limit.

    Construct via ``for_file`` (known file size) or ``for_request`` (whole
    request / multipart pre-check without a measured file size). The message
    is class-composed so presentation may render it directly.
    """

    def __init__(self, *, limit_bytes: int, actual_bytes: int | None) -> None:
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

    @classmethod
    def for_file(cls, *, limit_bytes: int, actual_bytes: int) -> "UploadTooLargeError":
        """Reject when a measured file (or stream total) exceeds the limit."""
        return cls(limit_bytes=limit_bytes, actual_bytes=actual_bytes)

    @classmethod
    def for_request(cls, *, limit_bytes: int) -> "UploadTooLargeError":
        """Reject a whole-request pre-check without asserting a file size."""
        return cls(limit_bytes=limit_bytes, actual_bytes=None)


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


class GoogleDriveNotConfiguredError(ConfigurationError):
    """Drive folder ID or service-account path is absent from runtime settings."""


class GoogleDriveOAuthNotConfiguredError(ConfigurationError):
    """User OAuth client ID, secret, or redirect URI is absent."""


class GoogleDriveNotConnectedError(ConfigurationError):
    """No user OAuth grant is stored for Google Drive."""


class GoogleDriveReauthorizationRequiredError(ConfigurationError):
    """The stored refresh token was revoked or is no longer valid."""


class GoogleDriveSelectionRequiredError(ConfigurationError):
    """A user grant exists but no Drive folder or file roots are saved."""


class InsufficientEvidenceError(RuntimeError):
    """A grounded use case found no retrieval hits above the relevance threshold.

    Expected outcome for flows such as requirements analysis where the caller
    supplied valid input but the corpus has nothing relevant enough to ground
    a model call. Presentation maps this type to a fixed user-safe sentence;
    diagnostic detail belongs on ``__cause__`` alone.
    """
