"""Public problem_from_exception taxonomy mapping."""

import pytest

from application.contracts import AskRequest
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
from domain.models import Message
from presentation.failure_messages import OPERATIONAL_FAILURE_MESSAGE
from presentation.http.errors import problem_from_exception


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (ApplicationValidationError("bad field"), 500, "operational_error"),
        (DomainValidationError("invariant"), 500, "operational_error"),
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


def test_application_validation_does_not_leak_exception_text() -> None:
    problem = problem_from_exception(
        ApplicationValidationError("Query must not be blank.")
    )

    assert problem.status == 500
    assert problem.code == "operational_error"
    assert problem.detail == OPERATIONAL_FAILURE_MESSAGE
    assert "Query must not be blank" not in problem.detail


def test_domain_validation_from_message_invariant_does_not_leak_content() -> None:
    with pytest.raises(DomainValidationError) as caught:
        Message(role="bogus", content="secret-corpus-text")

    problem = problem_from_exception(caught.value)
    body = problem.model_dump_json()

    assert problem.status == 500
    assert problem.code == "operational_error"
    assert problem.detail == OPERATIONAL_FAILURE_MESSAGE
    assert "secret-corpus-text" not in body
    assert "bogus" not in body


def test_application_validation_from_ask_history_does_not_leak_turn_text() -> None:
    sensitive = "secret-user-turn-text"
    with pytest.raises(ApplicationValidationError) as caught:
        AskRequest(query="ok", history=[sensitive])  # type: ignore[list-item]

    problem = problem_from_exception(caught.value)
    body = problem.model_dump_json()

    assert problem.status == 500
    assert problem.code == "operational_error"
    assert problem.detail == OPERATIONAL_FAILURE_MESSAGE
    assert sensitive not in body
