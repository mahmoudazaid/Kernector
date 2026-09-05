"""RFC 9457 Problem Details mapping for the HTTP presentation adapter."""

from __future__ import annotations

from pydantic import BaseModel

from application.errors import (
    ApplicationValidationError,
    ConfigurationError,
    InputRejectedError,
    InsufficientEvidenceError,
    OllamaNotConfiguredError,
)
from composition.errors import (
    DocumentContentError,
    DocumentOperationError,
    DocumentUploadError,
    KnowledgeLoadError,
    PartialDocumentOperationError,
    UnknownUploadedDocumentError,
)
from domain.errors import (
    DomainValidationError,
    ProviderError,
    ToolFailureError,
    VectorStoreError,
)
from presentation.failure_messages import (
    OPERATIONAL_FAILURE_MESSAGE,
    PROVIDER_FAILURE_MESSAGE,
    TOOL_FAILURE_MESSAGE,
)

_CONFIGURATION_FAILURE_DETAIL = "The service is not configured correctly."
_INSUFFICIENT_EVIDENCE_DETAIL = "Not enough relevant knowledge was found."
_INTERNAL_FAILURE_DETAIL = "An unexpected error occurred."
_VALIDATION_TITLE = "Request validation failed"
_PROBLEM_BASE = "https://kernector.dev/problems"

DOCUMENT_NOT_FOUND_DETAIL = "The requested document was not found."
DOCUMENT_UNREADABLE_DETAIL = (
    "The uploaded file has no extractable text. "
    "Try a different file or export it as plain text or Markdown."
)
UPLOAD_TOO_LARGE_DETAIL = "Upload must be at most {max_bytes} bytes."
DOCUMENT_PARTIAL_DETAILS = {
    "create": (
        "Upload failed and its status could not be saved; retry, or "
        "delete any visible pending document."
    ),
    "replace": "Replacement did not complete; retry Replace or Delete.",
    "delete": "Retry Delete to finish removing the catalog row.",
}


class UploadTooLargeError(RuntimeError):
    """Request body exceeds the configured upload size limit."""

    def __init__(self, *, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__(UPLOAD_TOO_LARGE_DETAIL.format(max_bytes=max_bytes))


class UnsupportedDocumentTypeError(RuntimeError):
    """Upload suffix is outside the supported set."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class ProblemError(BaseModel):
    """Field-level Problem Details extension entry."""

    pointer: str
    detail: str


class Problem(BaseModel):
    """RFC 9457 Problem Details plus Kernector extensions."""

    type: str
    title: str
    status: int
    detail: str
    code: str
    instance: str | None = None
    request_id: str | None = None
    errors: list[ProblemError] | None = None


_PROBLEM_MEDIA_TYPE = "application/problem+json"

_PROBLEM_STATUS_DESCRIPTIONS: dict[int, str] = {
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    413: "Payload too large",
    422: "Validation error",
    500: "Server error",
    502: "Provider error",
}


def problem_responses(*status_codes: int) -> dict[int, dict]:
    """OpenAPI response map declaring ``application/problem+json`` only.

    Uses a ``$ref`` to ``Problem``. Call :func:`register_problem_schemas` from
    the app OpenAPI generator so the model is present under
    ``components.schemas`` — a bare ``$ref`` does not register it.
    """
    responses: dict[int, dict] = {}
    for code in status_codes:
        description = _PROBLEM_STATUS_DESCRIPTIONS.get(code, "Error")
        responses[code] = {
            "description": description,
            "content": {
                _PROBLEM_MEDIA_TYPE: {
                    "schema": {"$ref": "#/components/schemas/Problem"}
                }
            },
        }
    return responses


def register_problem_schemas(components_schemas: dict) -> None:
    """Merge ``Problem`` / ``ProblemError`` into an OpenAPI components map."""
    raw = Problem.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    for name, subschema in raw.pop("$defs", {}).items():
        components_schemas.setdefault(name, subschema)
    components_schemas.setdefault("Problem", raw)


def problem_from_exception(
    exc: BaseException,
    *,
    instance: str | None = None,
    request_id: str | None = None,
) -> Problem:
    """Map a domain/application/composition failure to sanitized Problem Details.

    Human-readable fields never include tracebacks, vendor bodies, prompts,
    document content, or ``repr`` of rejected values. Client field errors are
    already handled as 422 by Pydantic via :func:`problem_from_validation_errors`.
    ``InputRejectedError`` is a client rejection (unsafe query, over-length
    input) and maps to 422 with the boundary-authored ``str(error)``. Plain
    ``ApplicationValidationError`` / ``DomainValidationError`` that reach this
    mapper are internal contract violations (usually ``__post_init__`` invariants)
    and map to 500 with the fixed operational sentence — matching Streamlit's
    ``DomainValidationError`` handling. Provider/tool/store failures use their
    fixed category sentences.
    """
    if isinstance(exc, InputRejectedError):
        return _problem(
            code="invalid_query",
            title="Invalid query",
            status=422,
            detail=str(exc),
            instance=instance,
            request_id=request_id,
        )
    if isinstance(exc, UploadTooLargeError):
        return _problem(
            code="upload_too_large",
            title="Payload too large",
            status=413,
            detail=UPLOAD_TOO_LARGE_DETAIL.format(max_bytes=exc.max_bytes),
            instance=instance,
            request_id=request_id,
        )
    if isinstance(exc, UnsupportedDocumentTypeError):
        return _problem(
            code="unsupported_document_type",
            title="Unsupported document type",
            status=422,
            detail=exc.detail,
            instance=instance,
            request_id=request_id,
        )
    if isinstance(exc, UnknownUploadedDocumentError):
        return _problem(
            code="document_not_found",
            title="Document not found",
            status=404,
            detail=DOCUMENT_NOT_FOUND_DETAIL,
            instance=instance,
            request_id=request_id,
        )
    if isinstance(exc, DocumentContentError):
        return _problem(
            code="document_unreadable",
            title="Document unreadable",
            status=422,
            detail=DOCUMENT_UNREADABLE_DETAIL,
            instance=instance,
            request_id=request_id,
        )
    if isinstance(exc, PartialDocumentOperationError):
        return _problem(
            code="document_partial_failure",
            title="Document partial failure",
            status=409,
            detail=DOCUMENT_PARTIAL_DETAILS[exc.operation],
            instance=instance,
            request_id=request_id,
        )
    if isinstance(exc, (ApplicationValidationError, DomainValidationError)):
        return _problem(
            code="operational_error",
            title="Operational error",
            status=500,
            detail=OPERATIONAL_FAILURE_MESSAGE,
            instance=instance,
            request_id=request_id,
        )
    if isinstance(exc, InsufficientEvidenceError):
        return _problem(
            code="insufficient_evidence",
            title="Insufficient evidence",
            status=422,
            detail=_INSUFFICIENT_EVIDENCE_DETAIL,
            instance=instance,
            request_id=request_id,
        )
    if isinstance(exc, OllamaNotConfiguredError):
        return _problem(
            code="ollama_unconfigured",
            title="Ollama not configured",
            status=409,
            detail="Ollama base URL is not configured on the server.",
            instance=instance,
            request_id=request_id,
        )
    if isinstance(exc, ConfigurationError):
        return _problem(
            code="configuration_error",
            title="Configuration error",
            status=500,
            detail=_CONFIGURATION_FAILURE_DETAIL,
            instance=instance,
            request_id=request_id,
        )
    if isinstance(exc, ProviderError):
        return _problem(
            code="provider_error",
            title="Provider error",
            status=502,
            detail=PROVIDER_FAILURE_MESSAGE,
            instance=instance,
            request_id=request_id,
        )
    if isinstance(exc, ToolFailureError):
        return _problem(
            code="tool_failure",
            title="Tool failure",
            status=500,
            detail=TOOL_FAILURE_MESSAGE,
            instance=instance,
            request_id=request_id,
        )
    if isinstance(exc, VectorStoreError):
        return _problem(
            code="store_error",
            title="Store error",
            status=500,
            detail=OPERATIONAL_FAILURE_MESSAGE,
            instance=instance,
            request_id=request_id,
        )
    if isinstance(
        exc,
        (KnowledgeLoadError, DocumentUploadError, DocumentOperationError),
    ):
        return _problem(
            code="operational_error",
            title="Operational error",
            status=500,
            detail=OPERATIONAL_FAILURE_MESSAGE,
            instance=instance,
            request_id=request_id,
        )
    return _problem(
        code="internal_error",
        title="Internal error",
        status=500,
        detail=_INTERNAL_FAILURE_DETAIL,
        instance=instance,
        request_id=request_id,
    )


def problem_from_validation_errors(
    errors: list[ProblemError],
    *,
    instance: str | None = None,
    request_id: str | None = None,
) -> Problem:
    """Build a 422 Problem Details body for request/schema validation failures."""
    return _problem(
        code="validation_error",
        title=_VALIDATION_TITLE,
        status=422,
        detail="One or more fields are invalid.",
        instance=instance,
        request_id=request_id,
        errors=errors,
    )


def _problem(
    *,
    code: str,
    title: str,
    status: int,
    detail: str,
    instance: str | None,
    request_id: str | None,
    errors: list[ProblemError] | None = None,
) -> Problem:
    return Problem(
        type=f"{_PROBLEM_BASE}/{code}",
        title=title,
        status=status,
        detail=detail,
        code=code,
        instance=instance,
        request_id=request_id,
        errors=errors,
    )
