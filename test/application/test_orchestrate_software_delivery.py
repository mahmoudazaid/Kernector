"""OrchestrateSoftwareDelivery: retrieve evidence, then invoke SD tools."""

from collections.abc import Mapping, Sequence

import pytest

from application.citations import build_citations
from application.contracts import (
    InvokeToolRequest,
    InvokeToolResponse,
    OrchestrateSoftwareDeliveryRequest,
    RetrieveRequest,
    RewriteRetrieveResponse,
    SoftwareDeliveryIntent,
)
from application.errors import ApplicationValidationError
from application.grounded_rag_policy import INSUFFICIENT_KNOWLEDGE_ANSWER
from application.orchestrate_software_delivery import (
    EXPORT_TEST_CASES_MARKDOWN,
    GENERATE_TEST_CASES,
    RISK_SCORE,
    OrchestrateSoftwareDelivery,
)
from domain.errors import ToolFailureError
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
)
THRESHOLD = 0.5
MAX_INPUT = 100


def _hit(
    *,
    source_id: str = "US-1",
    source_type: str = "user_story",
    content: str = "Need MFA on login",
    score: float = 0.9,
) -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(SourceReference(source_id, source_type)),
            index=0,
            content=content,
        ),
        score=score,
    )


class _FakeRewriteRetrieve:
    def __init__(self, hits: Sequence[ScoredChunk]) -> None:
        self._hits = tuple(hits)
        self.requests: list[object] = []

    def execute(self, request: object) -> RewriteRetrieveResponse:
        self.requests.append(request)
        return RewriteRetrieveResponse(
            hits=self._hits,
            original_query="unused",
            rewritten_query="unused rewritten",
        )


class _RecordingInvokeTool:
    def __init__(self, results: Mapping[str, str] | None = None) -> None:
        self.calls: list[InvokeToolRequest] = []
        self._results = dict(results or {})

    def execute(self, request: InvokeToolRequest) -> InvokeToolResponse:
        self.calls.append(request)
        result = self._results.get(request.tool_name, '{"ok":true}')
        return InvokeToolResponse(request.tool_name, result)


class _SpyInvokeTool:
    def execute(self, request: InvokeToolRequest) -> InvokeToolResponse:
        raise AssertionError("invoke must not run")


def _use_case(
    hits: Sequence[ScoredChunk],
    invoke: object,
    *,
    threshold: float = THRESHOLD,
    max_input_length: int = MAX_INPUT,
    default_retrieval_limit: int = 5,
) -> OrchestrateSoftwareDelivery:
    return OrchestrateSoftwareDelivery(
        _FakeRewriteRetrieve(hits),  # type: ignore[arg-type]
        invoke,  # type: ignore[arg-type]
        default_retrieval_limit=default_retrieval_limit,
        relevance_threshold=threshold,
        max_input_length=max_input_length,
    )


def _request(
    intent: SoftwareDeliveryIntent = SoftwareDeliveryIntent.RISK_SCORE,
    **overrides: object,
) -> OrchestrateSoftwareDeliveryRequest:
    values: dict[str, object] = {
        "intent": intent,
        "target": "Assess MFA",
        "query": "MFA requirements",
    }
    values.update(overrides)
    return OrchestrateSoftwareDeliveryRequest(**values)  # type: ignore[arg-type]


def test_risk_score_intent_invokes_risk_score_with_hit_evidence() -> None:
    invoke = _RecordingInvokeTool({RISK_SCORE: '{"score":40}'})
    use_case = _use_case([_hit()], invoke)

    response = use_case.execute(_request())

    assert len(invoke.calls) == 1
    call = invoke.calls[0]
    assert call.tool_name == RISK_SCORE
    assert call.arguments["target"] == "Assess MFA"
    evidence = call.arguments["evidence"]
    assert isinstance(evidence, list)
    assert evidence[0]["source_id"] == "US-1"
    assert evidence[0]["source_type"] == "user_story"
    assert evidence[0]["text"] == "Need MFA on login"
    assert response.tool_outputs == (InvokeToolResponse(RISK_SCORE, '{"score":40}'),)
    assert response.citations == build_citations([_hit()])
    assert response.answer


def test_insufficient_evidence_does_not_invoke_tools() -> None:
    invoke = _SpyInvokeTool()
    use_case = _use_case([_hit(score=0.1)], invoke)

    response = use_case.execute(_request())

    assert response.answer == INSUFFICIENT_KNOWLEDGE_ANSWER
    assert response.tool_outputs == ()
    assert response.citations == ()


def test_generate_and_export_chains_and_preserves_provenance() -> None:
    generate_json = (
        '{"output_style":"steps","test_cases":[{'
        '"title":"Login MFA","steps":["open login"],"expected":"prompted",'
        '"references":[{"source_id":"US-1","source_type":"user_story"}]}]}'
    )
    invoke = _RecordingInvokeTool(
        {
            GENERATE_TEST_CASES: generate_json,
            EXPORT_TEST_CASES_MARKDOWN: "# Test Cases\n\n- `US-1` (user_story)\n",
        }
    )
    use_case = _use_case([_hit()], invoke)

    response = use_case.execute(_request(SoftwareDeliveryIntent.GENERATE_AND_EXPORT))

    assert [call.tool_name for call in invoke.calls] == [
        GENERATE_TEST_CASES,
        EXPORT_TEST_CASES_MARKDOWN,
    ]
    generate_args = invoke.calls[0].arguments
    assert generate_args["target"] == "Assess MFA"
    assert generate_args["output_style"] == "steps"
    export_args = invoke.calls[1].arguments
    assert set(export_args) == {"output_style", "test_cases"}
    assert export_args["output_style"] == "steps"
    cases = export_args["test_cases"]
    assert isinstance(cases, list)
    assert cases[0]["references"][0]["source_id"] == "US-1"  # type: ignore[index]
    assert response.tool_outputs[-1].result.find("US-1") != -1
    assert response.tool_outputs[0].result == generate_json


def test_generate_tests_invokes_only_generate() -> None:
    invoke = _RecordingInvokeTool({GENERATE_TEST_CASES: '{"output_style":"gherkin"}'})
    use_case = _use_case([_hit()], invoke)

    response = use_case.execute(
        _request(SoftwareDeliveryIntent.GENERATE_TESTS, output_style="gherkin")
    )

    assert [call.tool_name for call in invoke.calls] == [GENERATE_TEST_CASES]
    assert invoke.calls[0].arguments["output_style"] == "gherkin"
    assert len(response.tool_outputs) == 1
    assert response.tool_outputs[0].tool_name == GENERATE_TEST_CASES


def test_oversized_query_fails_before_retrieve_or_invoke() -> None:
    retrieve = _FakeRewriteRetrieve([_hit()])
    invoke = _SpyInvokeTool()
    use_case = OrchestrateSoftwareDelivery(
        retrieve,  # type: ignore[arg-type]
        invoke,  # type: ignore[arg-type]
        default_retrieval_limit=5,
        relevance_threshold=THRESHOLD,
        max_input_length=10,
    )

    with pytest.raises(ApplicationValidationError, match="query must be at most"):
        use_case.execute(
            OrchestrateSoftwareDeliveryRequest(
                intent=SoftwareDeliveryIntent.RISK_SCORE,
                target="ok",
                query="x" * 11,
            )
        )
    assert retrieve.requests == []


def test_invalid_generate_json_fails_before_export() -> None:
    invoke = _RecordingInvokeTool({GENERATE_TEST_CASES: "not-json"})
    use_case = _use_case([_hit()], invoke)

    with pytest.raises(ToolFailureError):
        use_case.execute(_request(SoftwareDeliveryIntent.GENERATE_AND_EXPORT))
    assert [call.tool_name for call in invoke.calls] == [GENERATE_TEST_CASES]


def test_retrieval_limit_is_forwarded() -> None:
    retrieve = _FakeRewriteRetrieve([_hit()])
    invoke = _RecordingInvokeTool()
    use_case = OrchestrateSoftwareDelivery(
        retrieve,  # type: ignore[arg-type]
        invoke,  # type: ignore[arg-type]
        default_retrieval_limit=5,
        relevance_threshold=THRESHOLD,
        max_input_length=MAX_INPUT,
    )
    use_case.execute(_request(retrieval_limit=3))
    request = retrieve.requests[0]
    assert isinstance(request, RetrieveRequest)
    assert request.retrieval_limit == 3
    assert request.query == "MFA requirements"
