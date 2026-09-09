"""EvaluateKnowledge.execute observed through public eval contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from application.contracts import (
    AskRequest,
    AskResponse,
    Citation,
    InvokeToolRequest,
    InvokeToolResponse,
    RetrieveRequest,
    RetrieveResponse,
    RunMeta,
)
from application.evaluate_knowledge import EvaluateKnowledge
from application.evaluation_contracts import (
    EVAL_SCHEMA_VERSION,
    REQUIRED_CASE_CLASSES,
    EvalCase,
    EvalCitationLabel,
    EvalReport,
)
from application.grounded_rag_policy import INSUFFICIENT_KNOWLEDGE_ANSWER
from application.observed_rag import AnswerModelMetadata, RagObservation
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
    SourceType,
)


class _Unused:
    def execute(self, request: object) -> object:
        raise AssertionError("collaborator must not be called")


class _FakeRetrieve:
    def __init__(self, hits: Sequence[ScoredChunk] | Mapping[str, Sequence[ScoredChunk]]) -> None:
        self._hits = hits

    def execute(self, request: RetrieveRequest) -> RetrieveResponse:
        if isinstance(self._hits, Mapping):
            return RetrieveResponse(hits=self._hits.get(request.query, ()))
        return RetrieveResponse(hits=self._hits)


class _FakeAsk:
    def __init__(self, response: AskResponse | Mapping[str, AskResponse]) -> None:
        self._response = response

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        del settings
        if isinstance(self._response, Mapping):
            return self._response[request.query]
        return self._response


class _FakeInvoke:
    def __init__(
        self,
        response: InvokeToolResponse | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._response = response
        self._error = error

    def execute(self, request: InvokeToolRequest) -> InvokeToolResponse:
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _hit(
    source_id: str,
    *,
    source_type: str = SourceType.KNOWLEDGE_DOCUMENT,
    index: int = 0,
    content: str = "chunk",
    score: float = 1.0,
) -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(SourceReference(source_id, source_type)),
            index=index,
            content=content,
        ),
        score=score,
    )


def _citation(
    source_id: str,
    *,
    source_type: str = SourceType.KNOWLEDGE_DOCUMENT,
    chunk_index: int | None = 0,
    quote: str = "chunk",
) -> Citation:
    return Citation(
        SourceReference(source_id, source_type),
        quote=quote,
        chunk_index=chunk_index,
    )


def _retrieve_case(
    case_id: str = "r1",
    *,
    case_class: str = "single_source",
    query: str = "checkout retry",
    k: int = 5,
    expected_source_ids: Sequence[str] = ("checkout-retry",),
) -> EvalCase:
    return EvalCase(
        id=case_id,
        case_class=case_class,
        kind="retrieve",
        query=query,
        k=k,
        expected_source_ids=expected_source_ids,
    )


def _ask_case(
    case_id: str,
    *,
    case_class: str,
    query: str,
    k: int = 5,
    expected_answer_mode: str = "grounded",
    expected_source_ids: Sequence[str] | None = ("doc-a",),
    expected_citations: Sequence[EvalCitationLabel] = (),
) -> EvalCase:
    return EvalCase(
        id=case_id,
        case_class=case_class,
        kind="ask",
        query=query,
        k=k,
        expected_answer_mode=expected_answer_mode,
        expected_source_ids=expected_source_ids,
        expected_citations=expected_citations,
    )


class _FakeObservedRag:
    def __init__(self, observation: RagObservation | Mapping[str, RagObservation]) -> None:
        self._observation = observation
        self.calls: list[EvalCase] = []

    def execute(self, case: EvalCase) -> RagObservation:
        self.calls.append(case)
        if isinstance(self._observation, Mapping):
            return self._observation[case.query]
        return self._observation


def _answer_meta() -> AnswerModelMetadata:
    return AnswerModelMetadata(provider="eval-offline", model="eval-offline")


def _observation(
    case: EvalCase,
    response: AskResponse,
    hits: Sequence[ScoredChunk] = (),
) -> RagObservation:
    return RagObservation(
        case_id=case.id,
        query=case.query or "",
        answer=response.answer,
        citations=response.citations,
        retrieved_contexts=hits,
        run=response.run,
        answer_model=_answer_meta(),
    )


def _evaluate(
    *,
    retrieve: object = None,
    ask_pack_off: object = None,
    invoke: object | None = None,
    observed_rag: object | None = None,
) -> EvaluateKnowledge:
    return EvaluateKnowledge(
        retrieve=retrieve if retrieve is not None else _Unused(),
        ask_pack_off=ask_pack_off if ask_pack_off is not None else _Unused(),
        invoke=invoke,
        observed_rag=observed_rag,
    )


def test_empty_suite_reports_offline_zeros_and_skips_every_class() -> None:
    report = _evaluate().execute(())

    assert report.schema_version == EVAL_SCHEMA_VERSION
    assert report.mode == "offline"
    assert report.results == ()
    assert report.pass_count == 0
    assert report.fail_count == 0
    assert report.skip_count == 0
    assert report.aggregates["hit_at_k"].value == 0.0
    assert report.aggregates["hit_at_k"].denominator == 0
    assert report.aggregates["mrr"].value == 0.0
    assert report.aggregates["mrr"].denominator == 0
    assert report.aggregates["source_recall_at_k"].value == 0.0
    assert report.aggregates["source_recall_at_k"].denominator == 0
    assert tuple(report.coverage) == REQUIRED_CASE_CLASSES
    for entry in report.coverage.values():
        assert entry.state == "skipped"
        assert entry.reason == "no_case_configured"


def test_single_source_retrieve_scores_hit_mrr_and_recall_literals() -> None:
    report = _evaluate(
        retrieve=_FakeRetrieve((_hit("other"), _hit("checkout-retry"), _hit("noise"))),
    ).execute((_retrieve_case(k=3),))

    result = report.results[0]
    assert result.status == "pass"
    assert result.metrics["hit_at_k"] == 1.0
    assert result.metrics["mrr"] == 0.5
    assert result.metrics["source_recall_at_k"] == 1.0
    assert report.aggregates["hit_at_k"].value == 1.0
    assert report.aggregates["hit_at_k"].denominator == 1
    assert report.aggregates["mrr"].value == 0.5
    assert report.aggregates["mrr"].denominator == 1
    assert report.coverage["single_source"].state == "exercised"
    assert report.coverage["single_source"].reason is None


def test_single_source_retrieve_miss_scores_zeros_and_fails() -> None:
    report = _evaluate(retrieve=_FakeRetrieve((_hit("other"),))).execute(
        (_retrieve_case(k=1),)
    )

    result = report.results[0]
    assert result.status == "fail"
    assert result.metrics["hit_at_k"] == 0.0
    assert result.metrics["mrr"] == 0.0
    assert result.metrics["source_recall_at_k"] == 0.0
    assert result.checks["hit_at_k"] is False
    assert "hit_at_k" in result.failed_checks
    assert report.aggregates["hit_at_k"].value == 0.0
    assert report.aggregates["hit_at_k"].denominator == 1


def test_cross_source_retrieve_fails_when_hit_is_one_and_recall_is_not() -> None:
    report = _evaluate(retrieve=_FakeRetrieve((_hit("doc-a"), _hit("other")))).execute(
        (
            _retrieve_case(
                "cross-1",
                case_class="cross_source",
                query="payment timeout",
                expected_source_ids=("doc-a", "doc-b"),
            ),
        )
    )

    result = report.results[0]
    assert result.status == "fail"
    assert result.metrics["hit_at_k"] == 1.0
    assert result.metrics["mrr"] == 1.0
    assert result.metrics["source_recall_at_k"] == 0.5
    assert result.checks["source_recall_at_k"] is False
    assert "source_recall_at_k" in result.failed_checks


def test_cross_source_retrieve_passes_only_when_recall_is_one() -> None:
    report = _evaluate(
        retrieve=_FakeRetrieve((_hit("doc-b"), _hit("doc-a"))),
    ).execute(
        (
            _retrieve_case(
                "cross-1",
                case_class="cross_source",
                query="payment timeout",
                expected_source_ids=("doc-a", "doc-b"),
            ),
        )
    )

    result = report.results[0]
    assert result.status == "pass"
    assert result.metrics["hit_at_k"] == 1.0
    assert result.metrics["mrr"] == 1.0
    assert result.metrics["source_recall_at_k"] == 1.0
    assert result.checks["source_recall_at_k"] is True


def test_retrieval_aggregates_exclude_skips_and_include_misses() -> None:
    invoke_case = EvalCase(
        id="tool-1",
        case_class="tool",
        kind="invoke_tool",
        tool_name="software_delivery.risk_score",
        arguments={"target": "x", "evidence": []},
        expected_tool_result={"level": "high"},
    )
    miss = _retrieve_case("miss", query="missing", expected_source_ids=("absent",))
    hit = _retrieve_case(
        "hit",
        query="found",
        expected_source_ids=("checkout-retry",),
    )
    report = _evaluate(
        retrieve=_FakeRetrieve(
            {
                "missing": (_hit("other"),),
                "found": (_hit("checkout-retry"),),
            }
        ),
        invoke=None,
    ).execute((miss, invoke_case, hit))

    assert report.skip_count == 1
    assert report.fail_count == 1
    assert report.pass_count == 1
    assert report.results[1].status == "skip"
    assert report.results[1].skip_reason == "tool_unavailable"
    assert report.aggregates["hit_at_k"].denominator == 2
    assert report.aggregates["hit_at_k"].value == 0.5
    assert report.aggregates["mrr"].value == 0.5
    assert report.aggregates["source_recall_at_k"].value == 0.5
    assert report.coverage["tool"].state == "skipped"
    assert report.coverage["tool"].reason == "tool_unavailable"


def test_irrelevant_ask_requires_sentinel_empty_citations_and_insufficient_outcome() -> None:
    query = "xylophone nebula flamingo"
    case = _ask_case(
        "irr-1",
        case_class="irrelevant",
        query=query,
        expected_answer_mode="insufficient",
        expected_source_ids=None,
        expected_citations=(),
    )
    ask = AskResponse(
        answer=INSUFFICIENT_KNOWLEDGE_ANSWER,
        citations=(),
        run=RunMeta(outcome="insufficient", hit_count=0),
    )
    report = _evaluate(
        retrieve=_Unused(),
        observed_rag=_FakeObservedRag(_observation(case, ask, ())),
    ).execute((case,))

    result = report.results[0]
    assert result.status == "pass"
    assert result.checks["answer_insufficient"] is True
    assert result.checks["empty_citations"] is True
    assert result.checks["outcome_insufficient"] is True
    assert result.checks["shared_retrieve_hits"] is True
    assert report.aggregates["hit_at_k"].denominator == 0


def test_grounded_ask_requires_citation_precision_and_recall() -> None:
    query = "checkout retry"
    gold = EvalCitationLabel("doc-a", SourceType.KNOWLEDGE_DOCUMENT, chunk_index=0)
    hits = (_hit("doc-a"),)
    case = _ask_case(
        "cite-1",
        case_class="citation_provenance",
        query=query,
        expected_citations=(gold,),
    )
    ask = AskResponse(
        answer="Use exponential backoff.",
        citations=(_citation("doc-a"),),
        run=RunMeta(outcome="success", hit_count=1),
    )
    report = _evaluate(
        retrieve=_Unused(),
        observed_rag=_FakeObservedRag(_observation(case, ask, hits)),
    ).execute((case,))

    result = report.results[0]
    assert result.status == "pass"
    assert result.checks["citation_hit_precision"] is True
    assert result.checks["citation_gold_recall"] is True
    assert result.checks["citation_gold_precision"] is True
    assert result.checks["shared_retrieve_hits"] is True
    assert result.metrics["hit_at_k"] == 1.0


def test_ask_does_not_call_retrieve_seam() -> None:
    gold = EvalCitationLabel("doc-a", SourceType.KNOWLEDGE_DOCUMENT, chunk_index=0)
    case = _ask_case(
        "cite-same-run",
        case_class="citation_provenance",
        query="checkout retry",
        expected_citations=(gold,),
    )
    ask = AskResponse(
        answer="Use exponential backoff.",
        citations=(_citation("doc-a"),),
        run=RunMeta(outcome="success", hit_count=1),
    )
    retrieve = _Unused()
    report = _evaluate(
        retrieve=retrieve,
        observed_rag=_FakeObservedRag(_observation(case, ask, (_hit("doc-a"),))),
    ).execute((case,))

    assert report.results[0].status == "pass"
    assert report.results[0].checks["shared_retrieve_hits"] is True


def test_shared_retrieve_hits_fails_when_hit_count_mismatches_contexts() -> None:
    gold = EvalCitationLabel("doc-a", SourceType.KNOWLEDGE_DOCUMENT, chunk_index=0)
    case = _ask_case(
        "cite-mismatch",
        case_class="citation_provenance",
        query="checkout retry",
        expected_citations=(gold,),
    )
    ask = AskResponse(
        answer="Use exponential backoff.",
        citations=(_citation("doc-a"),),
        run=RunMeta(outcome="success", hit_count=2),
    )
    report = _evaluate(
        retrieve=_Unused(),
        observed_rag=_FakeObservedRag(_observation(case, ask, (_hit("doc-a"),))),
    ).execute((case,))

    result = report.results[0]
    assert result.checks["shared_retrieve_hits"] is False
    assert result.status == "fail"


def test_unexpected_citation_versus_gold_fails_gold_precision() -> None:
    gold = EvalCitationLabel("doc-a", SourceType.KNOWLEDGE_DOCUMENT, chunk_index=0)
    case = _ask_case(
        "cite-2",
        case_class="citation_provenance",
        query="q",
        expected_citations=(gold,),
    )
    ask = AskResponse(
        answer="An answer.",
        citations=(_citation("doc-a"), _citation("doc-extra")),
        run=RunMeta(outcome="success", hit_count=2),
    )
    report = _evaluate(
        observed_rag=_FakeObservedRag(
            _observation(case, ask, (_hit("doc-a"), _hit("doc-extra")))
        ),
    ).execute((case,))

    result = report.results[0]
    assert result.status == "fail"
    assert result.checks["citation_gold_precision"] is False
    assert "citation_gold_precision" in result.failed_checks


def test_unexpected_citation_versus_retrieve_hits_fails_hit_precision() -> None:
    gold = EvalCitationLabel("ghost", SourceType.KNOWLEDGE_DOCUMENT, chunk_index=0)
    case = _ask_case(
        "cite-3",
        case_class="citation_provenance",
        query="q",
        expected_source_ids=("doc-a",),
        expected_citations=(gold,),
    )
    ask = AskResponse(
        answer="An answer.",
        citations=(_citation("ghost"),),
        run=RunMeta(outcome="success", hit_count=1),
    )
    report = _evaluate(
        observed_rag=_FakeObservedRag(_observation(case, ask, (_hit("doc-a"),))),
    ).execute((case,))

    result = report.results[0]
    assert result.status == "fail"
    assert result.checks["citation_hit_precision"] is False
    assert "citation_hit_precision" in result.failed_checks


def test_conflicting_ask_requires_both_labeled_sources_retrieved_and_cited() -> None:
    query = "inventory SLA"
    labels = (
        EvalCitationLabel("sla-fast", SourceType.KNOWLEDGE_DOCUMENT),
        EvalCitationLabel("sla-slow", SourceType.KNOWLEDGE_DOCUMENT),
    )
    case = _ask_case(
        "conf-1",
        case_class="conflicting",
        query=query,
        expected_source_ids=("sla-fast", "sla-slow"),
        expected_citations=labels,
    )
    ask = AskResponse(
        answer="Sources disagree.",
        citations=(_citation("sla-fast", chunk_index=None), _citation("sla-slow", chunk_index=None)),
        run=RunMeta(outcome="success", hit_count=2),
    )
    report = _evaluate(
        observed_rag=_FakeObservedRag(
            _observation(case, ask, (_hit("sla-fast"), _hit("sla-slow")))
        ),
    ).execute((case,))

    result = report.results[0]
    assert result.status == "pass"
    assert result.checks["conflicting_sources_retrieved"] is True
    assert result.checks["conflicting_sources_cited"] is True


def test_unknown_source_kind_requires_labeled_type_retrieved_and_cited() -> None:
    query = "widget synchronizer"
    label = EvalCitationLabel("widget-sync", "future-connector", chunk_index=0)
    case = _ask_case(
        "unk-1",
        case_class="unknown_source_kind",
        query=query,
        expected_source_ids=("widget-sync",),
        expected_citations=(label,),
    )
    ask = AskResponse(
        answer="Handshake uses nonce tokens.",
        citations=(_citation("widget-sync", source_type="future-connector"),),
        run=RunMeta(outcome="success", hit_count=1),
    )
    report = _evaluate(
        observed_rag=_FakeObservedRag(
            _observation(
                case,
                ask,
                (_hit("widget-sync", source_type="future-connector"),),
            )
        ),
    ).execute((case,))

    result = report.results[0]
    assert result.status == "pass"
    assert result.checks["unknown_source_type_retrieved"] is True
    assert result.checks["unknown_source_type_cited"] is True


def test_pack_off_requires_empty_tools_rag_path_and_no_pack() -> None:
    ask = AskResponse(
        answer="Checkout retry uses backoff.",
        citations=(),
        tool_outputs=(),
        run=RunMeta(outcome="success", path="rag", pack=None),
    )
    report = _evaluate(ask_pack_off=_FakeAsk(ask)).execute(
        (
            EvalCase(
                id="pack-off-1",
                case_class="pack_off",
                kind="pack_off",
                query="assess the risk of checkout",
                k=5,
            ),
        )
    )

    result = report.results[0]
    assert result.status == "pass"
    assert result.checks["empty_tool_outputs"] is True
    assert result.checks["path_rag"] is True
    assert result.checks["pack_none"] is True
    assert report.aggregates["hit_at_k"].denominator == 0


def test_invoke_tool_passes_when_result_contains_expected_subset() -> None:
    report = _evaluate(
        invoke=_FakeInvoke(
            InvokeToolResponse(
                "software_delivery.risk_score",
                '{"level": "high", "score": 60, "rationale": "x"}',
            )
        )
    ).execute(
        (
            EvalCase(
                id="tool-1",
                case_class="tool",
                kind="invoke_tool",
                tool_name="software_delivery.risk_score",
                arguments={"target": "Assess authentication release risk"},
                expected_tool_result={"level": "high", "score": 60},
            ),
        )
    )

    result = report.results[0]
    assert result.status == "pass"
    assert result.checks["tool_name"] is True
    assert result.checks["tool_result_json"] is True
    assert result.checks["expected_tool_result"] is True
    assert report.coverage["tool"].state == "exercised"


def test_malformed_tool_json_fails_the_case_and_suite_continues() -> None:
    later = _retrieve_case("after")
    report = _evaluate(
        retrieve=_FakeRetrieve((_hit("checkout-retry"),)),
        invoke=_FakeInvoke(
            InvokeToolResponse("software_delivery.risk_score", "{not-json")
        ),
    ).execute(
        (
            EvalCase(
                id="tool-bad",
                case_class="tool",
                kind="invoke_tool",
                tool_name="software_delivery.risk_score",
                arguments={"target": "x"},
                expected_tool_result={"level": "high"},
            ),
            later,
        )
    )

    assert report.results[0].status == "fail"
    assert report.results[0].checks["tool_result_json"] is False
    assert "tool_result_json" in report.results[0].failed_checks
    assert report.results[1].status == "pass"
    assert report.fail_count == 1
    assert report.pass_count == 1


def test_invoke_none_skips_only_with_tool_unavailable() -> None:
    report = _evaluate(invoke=None).execute(
        (
            EvalCase(
                id="tool-1",
                case_class="tool",
                kind="invoke_tool",
                tool_name="software_delivery.risk_score",
                arguments={"target": "x"},
                expected_tool_result={"level": "high"},
            ),
        )
    )

    result = report.results[0]
    assert result.status == "skip"
    assert result.skip_reason == "tool_unavailable"
    assert report.skip_count == 1
    assert report.fail_count == 0
    assert report.coverage["tool"].state == "skipped"
    assert report.coverage["tool"].reason == "tool_unavailable"


def test_case_exception_fails_with_execution_error_and_remaining_cases_run() -> None:
    class _BoomRetrieve:
        def execute(self, request: RetrieveRequest) -> RetrieveResponse:
            if request.query == "checkout retry":
                raise RuntimeError("store down")
            return RetrieveResponse(hits=())

    later = _ask_case(
        "after",
        case_class="irrelevant",
        query="later",
        expected_answer_mode="insufficient",
        expected_source_ids=None,
    )
    ask = AskResponse(
        answer=INSUFFICIENT_KNOWLEDGE_ANSWER,
        run=RunMeta(outcome="insufficient", hit_count=0),
    )
    report = _evaluate(
        retrieve=_BoomRetrieve(),
        observed_rag=_FakeObservedRag(_observation(later, ask, ())),
    ).execute((_retrieve_case("boom"), later))

    assert report.results[0].status == "fail"
    assert report.results[0].failed_checks == ("execution_error",)
    assert report.results[0].checks["execution_error"] is False
    assert report.results[0].error_type == "RuntimeError"
    assert report.results[1].status == "pass"
    assert report.fail_count == 1
    assert report.pass_count == 1


def test_failed_case_still_marks_its_class_exercised() -> None:
    report = _evaluate(retrieve=_FakeRetrieve((_hit("other"),))).execute(
        (_retrieve_case(),)
    )

    assert report.results[0].status == "fail"
    assert report.coverage["single_source"].state == "exercised"
    assert report.coverage["single_source"].reason is None


def test_report_results_preserve_input_order() -> None:
    report = _evaluate(
        retrieve=_FakeRetrieve(
            {
                "second": (_hit("checkout-retry"),),
                "first": (_hit("checkout-retry"),),
            }
        )
    ).execute(
        (
            _retrieve_case("first", query="first"),
            _retrieve_case("second", query="second"),
        )
    )

    assert [result.case_id for result in report.results] == ["first", "second"]
    assert isinstance(report, EvalReport)
