"""RFC 9457 Problem Details mapping for the HTTP presentation adapter."""

from __future__ import annotations

from pydantic import BaseModel, Field

from application.errors import (
    ApplicationValidationError,
    ConfigurationError,
    InsufficientEvidenceError,
)
from composition.errors import (
    DocumentOperationError,
    DocumentUploadError,
    KnowledgeLoadError,
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
    errors: list[ProblemError] | None = Field(default=None)


def problem_from_exception(
    exc: BaseException,
    *,
    instance: str | None = None,
    request_id: str | None = None,
) -> Problem:
    """Map a domain/application/composition failure to sanitized Problem Details.

    Human-readable fields never include tracebacks, vendor bodies, or internal
    paths. Validation failures may carry boundary-authored ``str(exc)``; provider
    and operational failures use fixed category sentences (aligned with Streamlit).
    """
    if isinstance(exc, ApplicationValidationError):
        return _problem(
            code="validation_error",
            title=_VALIDATION_TITLE,
            status=422,
            detail=str(exc) or "One or more fields are invalid.",
            instance=instance,
            request_id=request_id,
        )
    if isinstance(exc, DomainValidationError):
        return _problem(
            code="validation_error",
            title=_VALIDATION_TITLE,
            status=422,
            detail=str(exc) or "One or more fields are invalid.",
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
