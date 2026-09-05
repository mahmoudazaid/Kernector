"""Public problem_from_exception taxonomy mapping."""

import pytest

from application.contracts import AskRequest
from application.errors import (
    ApplicationValidationError,
    ConfigurationError,
    InputRejectedError,
    InsufficientEvidenceError,
)
from application.input_safety import UNSAFE_QUERY_MESSAGE
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
from domain.models import Message
from presentation.failure_messages import OPERATIONAL_FAILURE_MESSAGE
from presentation.http.errors import (
    DOCUMENT_NOT_FOUND_DETAIL,
    DOCUMENT_PARTIAL_DETAILS,
    DOCUMENT_UNREADABLE_DETAIL,
    MISSING_UPLOAD_FILE_DETAIL,
    UPLOAD_TOO_LARGE_DETAIL,
    MissingUploadFileError,
    UnsupportedDocumentTypeError,
    UploadTooLargeError,
    problem_from_exception,
)


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


def test_input_rejected_maps_to_422_invalid_query_with_boundary_message() -> None:
    problem = problem_from_exception(InputRejectedError(UNSAFE_QUERY_MESSAGE))

    assert problem.status == 422
    assert problem.code == "invalid_query"
    assert problem.detail == UNSAFE_QUERY_MESSAGE
    assert problem.type == "https://kernector.dev/problems/invalid_query"


def test_plain_application_validation_still_maps_to_500() -> None:
    problem = problem_from_exception(ApplicationValidationError("bad field"))

    assert problem.status == 500
    assert problem.code == "operational_error"
    assert problem.detail == OPERATIONAL_FAILURE_MESSAGE


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


def test_unknown_uploaded_document_maps_to_404() -> None:
    problem = problem_from_exception(
        UnknownUploadedDocumentError("missing source id-xyz")
    )

    assert problem.status == 404
    assert problem.code == "document_not_found"
    assert problem.detail == DOCUMENT_NOT_FOUND_DETAIL
    assert "id-xyz" not in problem.detail


def test_plain_document_operation_error_still_maps_to_500() -> None:
    problem = problem_from_exception(
        DocumentOperationError("catalog path /var/secret/uploads.json")
    )

    assert problem.status == 500
    assert problem.code == "operational_error"
    assert problem.detail == OPERATIONAL_FAILURE_MESSAGE
    assert "/var/secret" not in problem.detail


def test_document_content_error_maps_to_422_unreadable() -> None:
    problem = problem_from_exception(
        DocumentContentError("/tmp/scan.pdf: no extractable text")
    )

    assert problem.status == 422
    assert problem.code == "document_unreadable"
    assert problem.detail == DOCUMENT_UNREADABLE_DETAIL
    assert "/tmp/scan.pdf" not in problem.detail


def test_document_upload_error_still_maps_to_500() -> None:
    problem = problem_from_exception(DocumentUploadError("extractor blew up"))

    assert problem.status == 500
    assert problem.code == "operational_error"
    assert problem.detail == OPERATIONAL_FAILURE_MESSAGE


@pytest.mark.parametrize(
    ("operation", "detail"),
    [
        ("create", DOCUMENT_PARTIAL_DETAILS["create"]),
        ("replace", DOCUMENT_PARTIAL_DETAILS["replace"]),
        ("delete", DOCUMENT_PARTIAL_DETAILS["delete"]),
    ],
)
def test_partial_document_operation_maps_to_409(
    operation: str, detail: str
) -> None:
    problem = problem_from_exception(
        PartialDocumentOperationError(
            "adapter leaked /var/chroma",
            operation=operation,  # type: ignore[arg-type]
        )
    )

    assert problem.status == 409
    assert problem.code == "document_partial_failure"
    assert problem.detail == detail
    assert "/var/chroma" not in problem.detail


def test_upload_too_large_maps_to_413() -> None:
    problem = problem_from_exception(UploadTooLargeError(max_bytes=5_242_880))

    assert problem.status == 413
    assert problem.code == "upload_too_large"
    assert problem.detail == UPLOAD_TOO_LARGE_DETAIL.format(max_bytes=5_242_880)


def test_unsupported_document_type_maps_to_422() -> None:
    detail = (
        "unsupported document type ('.docx'); supported types are "
        ".markdown, .md, .pdf, .txt"
    )
    problem = problem_from_exception(UnsupportedDocumentTypeError(detail))

    assert problem.status == 422
    assert problem.code == "unsupported_document_type"
    assert problem.detail == detail


def test_missing_upload_file_maps_to_422_with_streamlit_copy() -> None:
    problem = problem_from_exception(MissingUploadFileError())

    assert problem.status == 422
    assert problem.code == "missing_upload_file"
    assert problem.detail == MISSING_UPLOAD_FILE_DETAIL


def test_partial_document_unknown_operation_uses_fallback_detail() -> None:
    exc = PartialDocumentOperationError("half", operation="create")
    exc.operation = "unexpected"  # type: ignore[assignment]

    problem = problem_from_exception(exc)

    assert problem.status == 409
    assert problem.code == "document_partial_failure"
    assert "retry" in problem.detail.lower()
    assert problem.detail not in DOCUMENT_PARTIAL_DETAILS.values()
