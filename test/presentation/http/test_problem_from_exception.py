"""Public problem_from_exception taxonomy mapping."""

import pytest

from application.errors import (
    ApplicationValidationError,
    ConfigurationError,
    InsufficientEvidenceError,
)
from composition.errors import KnowledgeLoadError
from domain.errors import (
    DomainValidationError,
    ProviderError,
    ToolFailureError,
    VectorStoreError,
)
from presentation.http.errors import problem_from_exception


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (ApplicationValidationError("bad field"), 422, "validation_error"),
        (DomainValidationError("invariant"), 422, "validation_error"),
        (InsufficientEvidenceError("no hits"), 422, "insufficient_evidence"),
        (ConfigurationError("missing key"), 500, "configuration_error"),
        (ProviderError("upstream"), 502, "provider_error"),
        (ToolFailureError("tool broke"), 500, "tool_failure"),
        (VectorStoreError("chroma down"), 500, "store_error"),
        (KnowledgeLoadError("corpus"), 500, "operational_error"),
        (RuntimeError("mystery"), 500, "internal_error"),
    ],
)
def test_problem_from_exception_maps_taxonomy(
    exc: BaseException, status: int, code: str
) -> None:
    problem = problem_from_exception(exc)

    assert problem.status == status
    assert problem.code == code
    assert problem.type == f"https://kernector.dev/problems/{code}"
    assert "Traceback" not in problem.detail
    assert "Traceback" not in problem.title


def test_provider_error_uses_fixed_sanitized_detail() -> None:
    problem = problem_from_exception(ProviderError("sk-secret-token"))

    assert problem.detail == "The model provider could not complete the request."
    assert "sk-secret" not in problem.detail


def test_tool_failure_uses_fixed_sanitized_detail() -> None:
    problem = problem_from_exception(ToolFailureError("vendor body"))

    assert problem.detail == "A tool failed while processing your request."


def test_operational_errors_use_fixed_sanitized_detail() -> None:
    problem = problem_from_exception(VectorStoreError("internal path /var/chroma"))

    assert problem.detail == "Something went wrong while processing your request."
    assert "/var/chroma" not in problem.detail


def test_application_validation_preserves_boundary_authored_detail() -> None:
    problem = problem_from_exception(ApplicationValidationError("Query must not be blank."))

    assert problem.detail == "Query must not be blank."
    assert problem.status == 422
