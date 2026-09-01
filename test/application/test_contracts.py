"""Unit tests for application-layer request/response contracts."""

import importlib
import sys
from dataclasses import asdict

import pytest

from application.contracts import (
    AskRequest,
    AskResponse,
    Citation,
    IngestRequest,
    IngestResponse,
    InvokeToolRequest,
    InvokeToolResponse,
    RetrieveRequest,
    RetrieveResponse,
    RewriteRetrieveResponse,
    RunMeta,
)
from application.errors import ApplicationValidationError
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from domain.models import AskResult, Message, Usage

BLANK = ["", "   ", "\n"]


def _reference(source_id: str = "doc-1") -> SourceReference:
    return SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)


def _document(source_id: str = "doc-1") -> SourceDocument:
    return SourceDocument(
        SourceMetadata(_reference(source_id)),
        "knowledge content",
    )


def _citation() -> Citation:
    return Citation(_reference(), quote="relevant excerpt", chunk_index=0)


def _tool_output() -> InvokeToolResponse:
    return InvokeToolResponse("search", "2 hits")


def test_citation_constructs() -> None:
    citation = _citation()
    assert citation.reference.source_id == "doc-1"
    assert citation.quote == "relevant excerpt"
    assert citation.chunk_index == 0


def test_ask_request_has_no_ticket_field() -> None:
    assert "ticket" not in AskRequest.__dataclass_fields__


def test_ask_request_defaults_grounding_references_empty() -> None:
    request = AskRequest(prompt_key="default", query="What applies?")
    assert request.grounding_references == ()


def test_ask_request_accepts_grounding_references() -> None:
    references = [_reference("doc-1"), _reference("doc-2")]
    request = AskRequest(
        prompt_key="default",
        query="What applies?",
        grounding_references=references,
    )
    assert request.grounding_references == tuple(references)


def test_ask_request_accepts_opaque_non_blank_source_type() -> None:
    """Generic source contracts must not reject kinds absent from SourceType."""
    reference = SourceReference("x-1", "totally_unknown_kind")
    request = AskRequest(
        query="q",
        grounding_references=(reference,),
    )
    assert request.grounding_references[0].source_type == "totally_unknown_kind"


def test_ask_request_rejects_non_sequence_grounding_references() -> None:
    with pytest.raises(ApplicationValidationError, match="grounding_references"):
        AskRequest(
            prompt_key="default",
            query="What applies?",
            grounding_references=_reference(),  # type: ignore[arg-type]
        )


def test_ask_request_rejects_non_reference_grounding_item() -> None:
    with pytest.raises(
        ApplicationValidationError,
        match="grounding_references items must be SourceReference",
    ):
        AskRequest(
            prompt_key="default",
            query="What applies?",
            grounding_references=[_document()],  # type: ignore[list-item]
        )


def test_ask_request_grounding_references_are_independent_of_input_list() -> None:
    references = [_reference()]
    request = AskRequest(
        prompt_key="default",
        query="What applies?",
        grounding_references=references,
    )
    references.clear()
    assert request.grounding_references == (_reference(),)


def test_ask_request_constructs() -> None:
    history = [Message(role="user", content="earlier")]
    references = [_reference("doc-1"), _reference("doc-2")]
    request = AskRequest(
        prompt_key="default",
        query="What applies?",
        grounding_references=references,
        history=history,
        retrieval_limit=5,
    )
    assert request.prompt_key == "default"
    assert request.query == "What applies?"
    assert request.grounding_references == (
        _reference("doc-1"),
        _reference("doc-2"),
    )
    assert request.history == (Message(role="user", content="earlier"),)
    assert request.retrieval_limit == 5


def test_ask_request_allows_none_retrieval_limit() -> None:
    request = AskRequest(prompt_key="default", query="query")
    assert request.retrieval_limit is None


@pytest.mark.parametrize("limit", [1, 3, 100])
def test_ask_request_accepts_positive_retrieval_limit(limit: int) -> None:
    request = AskRequest(prompt_key="default", query="query", retrieval_limit=limit)
    assert request.retrieval_limit == limit


@pytest.mark.parametrize("bad_limit", [True, False, 0, -1, 1.5, "5", []])
def test_ask_request_rejects_invalid_retrieval_limit(bad_limit: object) -> None:
    with pytest.raises(ApplicationValidationError, match="retrieval_limit"):
        AskRequest(prompt_key="default", query="query", retrieval_limit=bad_limit)  # type: ignore[arg-type]


def test_ask_request_rejects_positional_construction() -> None:
    """`prompt_key` and `query` are both non-blank strings, so a positional swap
    would construct successfully and validate cleanly. Keyword-only is what makes
    that mistake impossible rather than merely unlikely."""
    with pytest.raises(TypeError):
        AskRequest("default", "query")  # type: ignore[misc]


def test_ask_request_requires_query() -> None:
    with pytest.raises(TypeError):
        AskRequest(prompt_key="default")  # type: ignore[call-arg]


def test_ask_request_allows_none_prompt_key() -> None:
    request = AskRequest(query="What applies?")
    assert request.prompt_key is None


def test_run_meta_defaults_are_empty() -> None:
    meta = RunMeta()
    assert meta.model is None
    assert meta.latency_ms is None
    assert meta.usage is None
    assert meta.settings == {}


def test_run_meta_from_result_drops_answer_content() -> None:
    result = AskResult(
        content="the answer text",
        model="test-model",
        latency_ms=42,
        usage=Usage(total_tokens=10),
        settings={"temperature": 0.3},
    )

    meta = RunMeta.from_result(result)

    assert meta.model == "test-model"
    assert meta.latency_ms == 42
    assert meta.usage == Usage(total_tokens=10)
    assert meta.settings == {"temperature": 0.3}
    assert "content" not in RunMeta.__dataclass_fields__
    assert "the answer text" not in str(meta)


def test_run_meta_rejects_negative_latency() -> None:
    with pytest.raises(ApplicationValidationError, match="latency_ms"):
        RunMeta(latency_ms=-1)


def test_ask_response_defaults_run_to_none() -> None:
    assert AskResponse("answer").run is None


def test_ask_response_accepts_run_meta() -> None:
    meta = RunMeta(model="test-model")
    assert AskResponse("answer", run=meta).run == meta


def test_ask_response_rejects_non_run_meta() -> None:
    with pytest.raises(ApplicationValidationError, match="run must be a RunMeta"):
        AskResponse("answer", run=AskResult(content="answer"))  # type: ignore[arg-type]


def test_ask_response_constructs() -> None:
    response = AskResponse(
        "Here is the analysis.",
        citations=[_citation()],
        tool_outputs=[_tool_output()],
    )
    assert response.answer == "Here is the analysis."
    assert response.citations == (_citation(),)
    assert response.tool_outputs == (_tool_output(),)


def test_ask_response_defaults_tool_outputs_empty() -> None:
    response = AskResponse("answer")
    assert response.tool_outputs == ()


def test_ingest_request_has_no_tickets_field() -> None:
    assert "tickets" not in IngestRequest.__dataclass_fields__


def test_ingest_request_constructs_with_documents() -> None:
    request = IngestRequest(documents=[_document()])
    assert request.documents == (_document(),)


def test_ingest_response_constructs() -> None:
    response = IngestResponse(["doc-1", "KRN-1"], 2)
    assert response.accepted_ids == ("doc-1", "KRN-1")
    assert response.chunk_count == 2


def test_invoke_tool_request_constructs() -> None:
    request = InvokeToolRequest("search", {"q": "login"})
    assert request.tool_name == "search"
    assert request.arguments == {"q": "login"}
    assert isinstance(request.arguments, dict)


def _scored_chunk() -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(_reference()),
            index=0,
            content="chunk text",
        ),
        score=0.9,
    )


def test_retrieve_request_constructs() -> None:
    request = RetrieveRequest(
        query="how do we restart?",
        retrieval_limit=5,
        metadata_filters={"doc_type": "runbook"},
    )
    assert request.query == "how do we restart?"
    assert request.retrieval_limit == 5
    assert request.metadata_filters == {"doc_type": "runbook"}
    assert isinstance(request.metadata_filters, dict)


def test_retrieve_request_defaults_metadata_filters_to_none() -> None:
    request = RetrieveRequest(query="what applies?", retrieval_limit=3)
    assert request.metadata_filters is None


def test_retrieve_request_accepts_empty_metadata_filters() -> None:
    request = RetrieveRequest(
        query="what applies?",
        retrieval_limit=3,
        metadata_filters={},
    )
    assert request.metadata_filters == {}


def test_retrieve_response_constructs() -> None:
    hit = _scored_chunk()
    response = RetrieveResponse(hits=[hit])
    assert response.hits == (hit,)


def test_retrieve_response_defaults_hits_empty() -> None:
    assert RetrieveResponse().hits == ()


def test_rewrite_retrieve_response_constructs() -> None:
    hit = _scored_chunk()
    response = RewriteRetrieveResponse(
        hits=[hit],
        original_query="what broke?",
        rewritten_query="payment service failure last week",
    )
    assert response.hits == (hit,)
    assert response.original_query == "what broke?"
    assert response.rewritten_query == "payment service failure last week"


def test_rewrite_retrieve_response_defaults_hits_empty() -> None:
    response = RewriteRetrieveResponse(
        original_query="what broke?",
        rewritten_query="payment service failure",
    )
    assert response.hits == ()


def test_invoke_tool_response_constructs() -> None:
    response = InvokeToolResponse("search", "2 hits")
    assert response.tool_name == "search"
    assert response.result == "2 hits"


def test_ask_request_accepts_none_prompt_key() -> None:
    request = AskRequest(prompt_key=None, query="What applies?")
    assert request.prompt_key is None
    assert request.query == "What applies?"


@pytest.mark.parametrize("blank", BLANK)
def test_ask_request_rejects_blank_prompt_key(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="prompt_key"):
        AskRequest(prompt_key=blank, query="query")


@pytest.mark.parametrize("blank", BLANK)
def test_ask_request_rejects_blank_query(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="query"):
        AskRequest(prompt_key="default", query=blank)


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
        AskRequest(prompt_key="default", query="query", history={"role": "user"})  # type: ignore[arg-type]


def test_ask_response_rejects_non_sequence_citations() -> None:
    with pytest.raises(ApplicationValidationError, match="citations"):
        AskResponse("answer", citations="cite")  # type: ignore[arg-type]


def test_ask_response_rejects_non_sequence_tool_outputs() -> None:
    with pytest.raises(ApplicationValidationError, match="tool_outputs"):
        AskResponse("answer", tool_outputs="tool")  # type: ignore[arg-type]


def test_ask_response_rejects_non_tool_output_item() -> None:
    with pytest.raises(ApplicationValidationError, match="tool_outputs items"):
        AskResponse("answer", tool_outputs=[_citation()])  # type: ignore[list-item]


def test_ingest_request_rejects_non_sequence_documents() -> None:
    with pytest.raises(ApplicationValidationError, match="documents"):
        IngestRequest(documents=_document())  # type: ignore[arg-type]


def test_ingest_response_rejects_non_sequence_accepted_ids() -> None:
    with pytest.raises(ApplicationValidationError, match="accepted_ids"):
        IngestResponse("doc-1", 1)  # type: ignore[arg-type]


def test_invoke_tool_request_rejects_non_mapping_arguments() -> None:
    with pytest.raises(ApplicationValidationError, match="arguments"):
        InvokeToolRequest("search", ["q"])  # type: ignore[arg-type]


@pytest.mark.parametrize("blank", BLANK)
def test_retrieve_request_rejects_blank_query(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="query"):
        RetrieveRequest(blank, retrieval_limit=3)


@pytest.mark.parametrize("bad_limit", [None, True, False, 0, -1, 1.5, "5", []])
def test_retrieve_request_rejects_invalid_retrieval_limit(bad_limit: object) -> None:
    with pytest.raises(ApplicationValidationError, match="retrieval_limit"):
        RetrieveRequest("query", retrieval_limit=bad_limit)  # type: ignore[arg-type]


@pytest.mark.parametrize("limit", [1, 3, 100])
def test_retrieve_request_accepts_positive_retrieval_limit(limit: int) -> None:
    assert RetrieveRequest("query", retrieval_limit=limit).retrieval_limit == limit


def test_retrieve_request_rejects_non_mapping_metadata_filters() -> None:
    with pytest.raises(ApplicationValidationError, match="metadata_filters"):
        RetrieveRequest(
            "query",
            retrieval_limit=3,
            metadata_filters=["doc_type"],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("bad_key", [1, "", "   ", None])
def test_retrieve_request_rejects_invalid_metadata_filter_keys(
    bad_key: object,
) -> None:
    with pytest.raises(ApplicationValidationError, match="metadata_filters keys"):
        RetrieveRequest(
            "query",
            retrieval_limit=3,
            metadata_filters={bad_key: "runbook"},  # type: ignore[dict-item]
        )


@pytest.mark.parametrize("bad_value", [1, None, True, ["x"], {"a": "b"}])
def test_retrieve_request_rejects_non_string_metadata_filter_values(
    bad_value: object,
) -> None:
    with pytest.raises(ApplicationValidationError, match="metadata_filters values"):
        RetrieveRequest(
            "query",
            retrieval_limit=3,
            metadata_filters={"doc_type": bad_value},  # type: ignore[dict-item]
        )


def test_retrieve_request_accepts_empty_string_filter_value() -> None:
    request = RetrieveRequest(
        "query",
        retrieval_limit=3,
        metadata_filters={"tag": ""},
    )
    assert request.metadata_filters == {"tag": ""}


def test_retrieve_response_rejects_non_sequence_hits() -> None:
    with pytest.raises(ApplicationValidationError, match="hits"):
        RetrieveResponse(hits="chunk")  # type: ignore[arg-type]


def test_retrieve_response_rejects_non_scored_chunk_item() -> None:
    with pytest.raises(ApplicationValidationError, match="hits items"):
        RetrieveResponse(hits=[_reference()])  # type: ignore[list-item]


@pytest.mark.parametrize("blank", BLANK)
def test_rewrite_retrieve_response_rejects_blank_original_query(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="original_query"):
        RewriteRetrieveResponse(
            original_query=blank,
            rewritten_query="rewritten",
        )


@pytest.mark.parametrize("blank", BLANK)
def test_rewrite_retrieve_response_rejects_blank_rewritten_query(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="rewritten_query"):
        RewriteRetrieveResponse(
            original_query="original",
            rewritten_query=blank,
        )


def test_rewrite_retrieve_response_rejects_non_sequence_hits() -> None:
    with pytest.raises(ApplicationValidationError, match="hits"):
        RewriteRetrieveResponse(
            hits="chunk",  # type: ignore[arg-type]
            original_query="original",
            rewritten_query="rewritten",
        )


def test_rewrite_retrieve_response_rejects_non_scored_chunk_item() -> None:
    with pytest.raises(ApplicationValidationError, match="hits items"):
        RewriteRetrieveResponse(
            hits=[_reference()],  # type: ignore[list-item]
            original_query="original",
            rewritten_query="rewritten",
        )


@pytest.mark.parametrize("bad_key", [1, "", "   ", None])
def test_invoke_tool_request_rejects_invalid_argument_keys(bad_key: object) -> None:
    with pytest.raises(ApplicationValidationError, match="arguments keys"):
        InvokeToolRequest("search", {bad_key: "v"})  # type: ignore[dict-item]


def test_ask_request_rejects_non_message_history_item() -> None:
    with pytest.raises(ApplicationValidationError, match="history items"):
        AskRequest(prompt_key="default", query="query", history=["hi"])  # type: ignore[list-item]


def test_ask_response_rejects_non_citation_item() -> None:
    with pytest.raises(ApplicationValidationError, match="citations items"):
        AskResponse("answer", citations=[_reference()])  # type: ignore[list-item]


def test_ingest_request_rejects_non_document_item() -> None:
    with pytest.raises(ApplicationValidationError, match="documents items"):
        IngestRequest(documents=[_reference()])  # type: ignore[list-item]


def test_ingest_request_rejects_empty_documents() -> None:
    with pytest.raises(ApplicationValidationError, match="documents must contain at least one item"):
        IngestRequest()


@pytest.mark.parametrize("blank", BLANK)
def test_ingest_response_rejects_blank_accepted_ids(blank: str) -> None:
    with pytest.raises(ApplicationValidationError, match="accepted_ids item"):
        IngestResponse([blank], 1)


def test_ingest_response_requires_a_chunk_count() -> None:
    """A missing count must fail at the call, never default to zero."""
    with pytest.raises(TypeError):
        IngestResponse(["doc-1"])  # type: ignore[call-arg]


@pytest.mark.parametrize("bad_count", [-1, True, "3", 1.5, None])
def test_ingest_response_rejects_invalid_chunk_count(bad_count: object) -> None:
    with pytest.raises(ApplicationValidationError, match="chunk_count"):
        IngestResponse(["doc-1"], bad_count)  # type: ignore[arg-type]


def test_ingest_response_accepts_a_zero_chunk_count() -> None:
    """Explicitly passing zero is legal; silently defaulting to it is not."""
    assert IngestResponse(["doc-1"], 0).chunk_count == 0


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
    request = AskRequest(prompt_key="default", query="query", history=[Message("user", "hi")])
    response = AskResponse("answer", citations=[_citation()])
    with pytest.raises(AttributeError):
        request.query = "changed"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        response.answer = "changed"  # type: ignore[misc]


def test_ask_request_history_is_independent_of_input_list() -> None:
    history = [Message(role="user", content="hi")]
    request = AskRequest(prompt_key="default", query="query", history=history)
    history.append(Message(role="assistant", content="ok"))
    assert request.history == (Message(role="user", content="hi"),)


def test_ask_response_citations_are_independent_of_input_list() -> None:
    citations = [_citation()]
    response = AskResponse("answer", citations=citations)
    citations.clear()
    assert len(response.citations) == 1


def test_ask_response_tool_outputs_are_independent_of_input_list() -> None:
    outputs = [_tool_output()]
    response = AskResponse("answer", tool_outputs=outputs)
    outputs.clear()
    assert response.tool_outputs == (_tool_output(),)


def test_ingest_request_documents_are_independent_of_input_list() -> None:
    documents = [_document()]
    request = IngestRequest(documents=documents)
    documents.clear()
    assert request.documents == (_document(),)


def test_ingest_response_ids_are_independent_of_input_list() -> None:
    ids = ["doc-1"]
    response = IngestResponse(ids, 1)
    ids.append("doc-2")
    assert response.accepted_ids == ("doc-1",)


def test_invoke_tool_arguments_are_copied() -> None:
    arguments = {"q": "login"}
    request = InvokeToolRequest("search", arguments)
    arguments["q"] = "logout"
    assert request.arguments == {"q": "login"}
    assert request.arguments is not arguments


def test_retrieve_request_metadata_filters_are_copied() -> None:
    filters = {"doc_type": "runbook"}
    request = RetrieveRequest(
        "query",
        retrieval_limit=3,
        metadata_filters=filters,
    )
    filters["doc_type"] = "changed"
    assert request.metadata_filters == {"doc_type": "runbook"}
    assert request.metadata_filters is not filters


def test_retrieve_response_hits_are_independent_of_input_list() -> None:
    hits = [_scored_chunk()]
    response = RetrieveResponse(hits=hits)
    hits.clear()
    assert len(response.hits) == 1


def test_rewrite_retrieve_response_hits_are_independent_of_input_list() -> None:
    hits = [_scored_chunk()]
    response = RewriteRetrieveResponse(
        hits=hits,
        original_query="original",
        rewritten_query="rewritten",
    )
    hits.clear()
    assert len(response.hits) == 1


def test_contracts_serialize_with_asdict() -> None:
    ask_request = AskRequest(
        prompt_key="default",
        query="query",
        grounding_references=[_reference()],
        history=[Message(role="user", content="hi")],
        retrieval_limit=3,
    )
    ask_response = AskResponse(
        "answer",
        citations=[_citation()],
        tool_outputs=[_tool_output()],
    )
    ingest_request = IngestRequest(documents=[_document()])
    ingest_response = IngestResponse(["doc-1"], 1)
    tool_request = InvokeToolRequest("search", {"q": "login"})
    tool_response = _tool_output()
    retrieve_request = RetrieveRequest(
        "query",
        retrieval_limit=5,
        metadata_filters={"doc_type": "runbook"},
    )
    retrieve_response = RetrieveResponse(hits=[_scored_chunk()])
    rewrite_retrieve_response = RewriteRetrieveResponse(
        hits=[_scored_chunk()],
        original_query="what broke?",
        rewritten_query="payment failure",
    )

    ask_dict = asdict(ask_request)
    assert "ticket" not in ask_dict
    assert ask_dict["retrieval_limit"] == 3
    assert ask_dict["history"] == ({"role": "user", "content": "hi"},)
    assert ask_dict["grounding_references"] == (
        {
            "source_id": "doc-1",
            "source_type": SourceType.KNOWLEDGE_DOCUMENT,
        },
    )
    assert asdict(ask_response)["citations"][0]["quote"] == "relevant excerpt"
    assert asdict(ask_response)["tool_outputs"] == (
        {"tool_name": "search", "result": "2 hits"},
    )
    ingest_dict = asdict(ingest_request)
    assert ingest_dict["documents"][0]["content"] == "knowledge content"
    assert "tickets" not in ingest_dict
    assert asdict(ingest_response) == {"accepted_ids": ("doc-1",), "chunk_count": 1}
    assert asdict(tool_request) == {
        "tool_name": "search",
        "arguments": {"q": "login"},
    }
    assert asdict(tool_response) == {"tool_name": "search", "result": "2 hits"}
    assert asdict(retrieve_request) == {
        "query": "query",
        "retrieval_limit": 5,
        "metadata_filters": {"doc_type": "runbook"},
    }
    assert asdict(retrieve_response)["hits"][0]["score"] == 0.9
    assert asdict(retrieve_response)["hits"][0]["chunk"]["content"] == "chunk text"
    assert asdict(rewrite_retrieve_response) == {
        "hits": asdict(retrieve_response)["hits"],
        "original_query": "what broke?",
        "rewritten_query": "payment failure",
    }


def test_application_contracts_import_without_streamlit() -> None:
    sys.modules.pop("application.contracts", None)
    module = importlib.import_module("application.contracts")
    assert "streamlit" not in sys.modules
    assert hasattr(module, "AskRequest")


def test_application_contracts_exclude_software_delivery_orchestration_types() -> None:
    import application.contracts as contracts

    forbidden = {
        "SoftwareDeliveryIntent",
        "OrchestrateSoftwareDeliveryRequest",
        "OrchestrateSoftwareDeliveryResponse",
    }
    assert forbidden.isdisjoint(set(dir(contracts)))

