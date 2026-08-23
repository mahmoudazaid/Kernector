"""Unit tests for application-layer request/response contracts."""

import importlib
import sys

import pytest

from application.contracts import (
    AskRequest,
    AskResponse,
    Citation,
    IngestRequest,
    IngestResponse,
    InvokeToolRequest,
    InvokeToolResponse,
)
from application.errors import ApplicationValidationError
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
    Ticket,
)
from domain.models import Message

BLANK = ["", "   ", "\n"]


def _reference(source_id: str = "doc-1") -> SourceReference:
    return SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)


def _document(source_id: str = "doc-1") -> SourceDocument:
    return SourceDocument(
        SourceMetadata(_reference(source_id)),
        "knowledge content",
    )


def _ticket(ticket_id: str = "KRN-1") -> Ticket:
    return Ticket(ticket_id, "As a QA analyst I want ...")


def _citation() -> Citation:
    return Citation(_reference(), quote="relevant excerpt", chunk_index=0)


def test_citation_constructs() -> None:
    citation = _citation()
    assert citation.reference.source_id == "doc-1"
    assert citation.quote == "relevant excerpt"
    assert citation.chunk_index == 0


def test_ask_request_constructs() -> None:
    history = [Message(role="user", content="earlier")]
    request = AskRequest(
        "default",
        "Analyze this ticket",
        ticket=_ticket(),
        history=history,
    )
    assert request.prompt_key == "default"
    assert request.query == "Analyze this ticket"
    assert request.ticket == _ticket()
    assert request.history == (Message(role="user", content="earlier"),)


def test_ask_response_constructs() -> None:
    response = AskResponse("Here is the analysis.", citations=[_citation()])
    assert response.answer == "Here is the analysis."
    assert response.citations == (_citation(),)


def test_ingest_request_constructs_with_documents() -> None:
    request = IngestRequest(documents=[_document()])
    assert request.documents == (_document(),)
    assert request.tickets == ()


def test_ingest_request_constructs_with_tickets() -> None:
    request = IngestRequest(tickets=[_ticket()])
    assert request.tickets == (_ticket(),)
    assert request.documents == ()


def test_ingest_response_constructs() -> None:
    response = IngestResponse(["doc-1", "KRN-1"])
    assert response.accepted_ids == ("doc-1", "KRN-1")


def test_invoke_tool_request_constructs() -> None:
    request = InvokeToolRequest("search", {"q": "login"})
    assert request.tool_name == "search"
    assert dict(request.arguments) == {"q": "login"}


def test_invoke_tool_response_constructs() -> None:
    response = InvokeToolResponse("search", "2 hits")
    assert response.tool_name == "search"
    assert response.result == "2 hits"


@pytest.mark.parametrize("blank", BLANK)
def test_ask_request_rejects_blank_prompt_key(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="prompt_key"):
        AskRequest(blank, "query")


@pytest.mark.parametrize("blank", BLANK)
def test_ask_request_rejects_blank_query(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="query"):
        AskRequest("default", blank)


@pytest.mark.parametrize("blank", BLANK)
def test_ask_response_rejects_blank_answer(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="answer"):
        AskResponse(blank)


@pytest.mark.parametrize("blank", BLANK)
def test_invoke_tool_request_rejects_blank_tool_name(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="tool_name"):
        InvokeToolRequest(blank, {})


@pytest.mark.parametrize("blank", BLANK)
def test_invoke_tool_response_rejects_blank_tool_name(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="tool_name"):
        InvokeToolResponse(blank, "ok")


@pytest.mark.parametrize("blank", BLANK)
def test_invoke_tool_response_rejects_blank_result(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="result"):
        InvokeToolResponse("search", blank)


def test_ask_request_rejects_non_sequence_history() -> None:
    with pytest.raises(ApplicationValidationError, match="history"):
        AskRequest("default", "query", history={"role": "user"})  # type: ignore[arg-type]


def test_ask_response_rejects_non_sequence_citations() -> None:
    with pytest.raises(ApplicationValidationError, match="citations"):
        AskResponse("answer", citations="cite")  # type: ignore[arg-type]


def test_ingest_request_rejects_non_sequence_documents() -> None:
    with pytest.raises(ApplicationValidationError, match="documents"):
        IngestRequest(documents=_document())  # type: ignore[arg-type]


def test_ingest_request_rejects_non_sequence_tickets() -> None:
    with pytest.raises(ApplicationValidationError, match="tickets"):
        IngestRequest(tickets=_ticket())  # type: ignore[arg-type]


def test_ingest_response_rejects_non_sequence_accepted_ids() -> None:
    with pytest.raises(ApplicationValidationError, match="accepted_ids"):
        IngestResponse("doc-1")  # type: ignore[arg-type]


def test_invoke_tool_request_rejects_non_mapping_arguments() -> None:
    with pytest.raises(ApplicationValidationError, match="arguments"):
        InvokeToolRequest("search", ["q"])  # type: ignore[arg-type]


def test_ask_request_rejects_non_ticket() -> None:
    with pytest.raises(ApplicationValidationError, match="ticket"):
        AskRequest("default", "query", ticket=_document())  # type: ignore[arg-type]


def test_ask_request_rejects_non_message_history_item() -> None:
    with pytest.raises(ApplicationValidationError, match="history items"):
        AskRequest("default", "query", history=["hi"])  # type: ignore[list-item]


def test_ask_response_rejects_non_citation_item() -> None:
    with pytest.raises(ApplicationValidationError, match="citations items"):
        AskResponse("answer", citations=[_reference()])  # type: ignore[list-item]


def test_ingest_request_rejects_non_document_item() -> None:
    with pytest.raises(ApplicationValidationError, match="documents items"):
        IngestRequest(documents=[_ticket()])  # type: ignore[list-item]


def test_ingest_request_rejects_non_ticket_item() -> None:
    with pytest.raises(ApplicationValidationError, match="tickets items"):
        IngestRequest(tickets=[_document()])  # type: ignore[list-item]


def test_ingest_request_rejects_empty_collections() -> None:
    with pytest.raises(ApplicationValidationError, match="documents or tickets"):
        IngestRequest()


@pytest.mark.parametrize("blank", BLANK)
def test_ingest_response_rejects_blank_accepted_ids(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="accepted_ids item"):
        IngestResponse([blank])


def test_citation_rejects_non_reference() -> None:
    with pytest.raises(ApplicationValidationError, match="reference"):
        Citation("doc-1")  # type: ignore[arg-type]


@pytest.mark.parametrize("blank", BLANK)
def test_citation_rejects_blank_quote(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="quote"):
        Citation(_reference(), quote=blank)


@pytest.mark.parametrize("bad_index", [-1, True, "0", 1.5])
def test_citation_rejects_invalid_chunk_index(bad_index: object) -> None:
    with pytest.raises(ApplicationValidationError, match="chunk_index"):
        Citation(_reference(), chunk_index=bad_index)  # type: ignore[arg-type]


def test_contracts_are_immutable() -> None:
    request = AskRequest("default", "query", history=[Message("user", "hi")])
    response = AskResponse("answer", citations=[_citation()])
    with pytest.raises(AttributeError):
        request.query = "changed"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        response.answer = "changed"  # type: ignore[misc]


def test_ask_request_history_is_independent_of_input_list() -> None:
    history = [Message(role="user", content="hi")]
    request = AskRequest("default", "query", history=history)
    history.append(Message(role="assistant", content="ok"))
    assert request.history == (Message(role="user", content="hi"),)


def test_ask_response_citations_are_independent_of_input_list() -> None:
    citations = [_citation()]
    response = AskResponse("answer", citations=citations)
    citations.clear()
    assert len(response.citations) == 1


def test_ingest_request_collections_are_independent_of_input_lists() -> None:
    documents = [_document()]
    tickets = [_ticket()]
    request = IngestRequest(documents=documents, tickets=tickets)
    documents.clear()
    tickets.clear()
    assert request.documents == (_document(),)
    assert request.tickets == (_ticket(),)


def test_ingest_response_ids_are_independent_of_input_list() -> None:
    ids = ["doc-1"]
    response = IngestResponse(ids)
    ids.append("doc-2")
    assert response.accepted_ids == ("doc-1",)


def test_invoke_tool_arguments_are_read_only_and_copied() -> None:
    arguments = {"q": "login"}
    request = InvokeToolRequest("search", arguments)
    arguments["q"] = "logout"
    assert request.arguments["q"] == "login"
    with pytest.raises(TypeError):
        request.arguments["extra"] = "no"  # type: ignore[index]


def test_application_contracts_import_without_streamlit() -> None:
    sys.modules.pop("application.contracts", None)
    module = importlib.import_module("application.contracts")
    assert "streamlit" not in sys.modules
    assert hasattr(module, "AskRequest")
