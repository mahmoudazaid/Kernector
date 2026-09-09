"""EvaluateRag judges ask cases only and aggregates scored metrics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from application.contracts import AskResponse, Citation, RunMeta
from application.evaluate_rag import EvaluateRag, parse_judge_output, rag_judge_report_to_csv
from application.evaluation_contracts import EvalCase, EvalCitationLabel
from application.observed_rag import AnswerModelMetadata, RagObservation
from application.rag_judge_contracts import (
    CSV_HEADERS,
    AnswerRunMetadata,
    JudgeMetadata,
    RagJudgeBaseline,
    RagJudgeFingerprints,
    RagJudgeThresholds,
)
from application.rag_judge_policy import METRIC_IDS, PROMPT_VERSION
from domain.errors import ProviderError
from domain.knowledge import DocumentChunk, ScoredChunk, SourceMetadata, SourceReference
from domain.models import AskResult


def _hit(source_id: str, *, source_type: str = "knowledge_document") -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(SourceReference(source_id, source_type)),
            index=0,
            content="chunk",
        ),
        score=1.0,
    )


def _citation(source_id: str, *, source_type: str = "knowledge_document") -> Citation:
    return Citation(SourceReference(source_id, source_type), quote="chunk", chunk_index=0)


def _fingerprints() -> RagJudgeFingerprints:
    return RagJudgeFingerprints(
        dataset_hash="d" * 64,
        corpus_hash="c" * 64,
        metric_set=METRIC_IDS,
        judge_provider="openrouter",
        judge_model="judge-model",
        prompt_version=PROMPT_VERSION,
        answer_provider="openrouter",
        answer_model="answer-model",
        embedding_model="embed-model",
        retrieval_limit=5,
        relevance_threshold=0.0,
        hybrid_enabled=True,
        hybrid_alpha=0.5,
        rewriter="openrouter-rewrite",
    )


def _judge_meta() -> JudgeMetadata:
    return JudgeMetadata(
        provider="openrouter",
        model="judge-model",
        prompt_version=PROMPT_VERSION,
        temperature=0,
    )


def _answer_meta() -> AnswerRunMetadata:
    return AnswerRunMetadata(provider="openrouter", model="answer-model")


def _baseline(*, accepted: bool = True) -> RagJudgeBaseline:
    return RagJudgeBaseline(
        accepted=accepted,
        means={name: 0.9 for name in METRIC_IDS},
        fingerprints=_fingerprints(),
        allowed_drop=0.05,
    )


def _ask_case(
    case_id: str,
    *,
    case_class: str,
    query: str = "q",
    slice: str = "core",
    expected_source_ids: Sequence[str] | None = ("doc-a",),
    expected_citations: Sequence[EvalCitationLabel] | None = None,
    expected_answer_mode: str = "grounded",
    reference_answer: str = "reference",
) -> EvalCase:
    if expected_citations is None and expected_answer_mode == "grounded":
        expected_citations = (EvalCitationLabel("doc-a", "knowledge_document", 0),)
    return EvalCase(
        id=case_id,
        case_class=case_class,
        kind="ask",
        query=query,
        k=5,
        expected_answer_mode=expected_answer_mode,
        expected_source_ids=expected_source_ids,
        expected_citations=expected_citations or (),
        slice=slice,
        reference_answer=reference_answer,
    )


def _observation(case: EvalCase, hits: Sequence[ScoredChunk], citations: Sequence[Citation]) -> RagObservation:
    return RagObservation(
        case_id=case.id,
        query=case.query or "",
        answer="visible answer",
        citations=citations,
        retrieved_contexts=hits,
        run=RunMeta(outcome="success", hit_count=len(hits)),
        answer_model=AnswerModelMetadata(provider="openrouter", model="answer-model"),
    )


class _ScriptedJudge:
    def __init__(self, content: str = '{"score": 0.8, "explanation": "ok"}') -> None:
        self.content = content
        self.calls: list[tuple[str, tuple, dict]] = []

    def complete(self, system: str, messages: Sequence[object], settings: Mapping[str, object]) -> AskResult:
        self.calls.append((system, tuple(messages), dict(settings)))
        return AskResult(content=self.content, model="judge-model")


def _coverage_cases() -> tuple[EvalCase, ...]:
    return (
        _ask_case(
            "cross",
            case_class="cross_source",
            expected_source_ids=("a", "b"),
            expected_citations=(
                EvalCitationLabel("a", "knowledge_document"),
                EvalCitationLabel("b", "knowledge_document"),
            ),
        ),
        _ask_case(
            "irr",
            case_class="irrelevant",
            expected_source_ids=None,
            expected_citations=(),
            expected_answer_mode="insufficient",
        ),
        _ask_case(
            "conf",
            case_class="conflicting",
            expected_source_ids=("a", "b"),
            expected_citations=(
                EvalCitationLabel("a", "knowledge_document"),
                EvalCitationLabel("b", "knowledge_document"),
            ),
        ),
        _ask_case(
            "unk",
            case_class="unknown_source_kind",
            expected_source_ids=("w",),
            expected_citations=(EvalCitationLabel("w", "future-connector", 0),),
        ),
        _ask_case("cite", case_class="citation_provenance"),
        _ask_case(
            "sd",
            case_class="citation_provenance",
            slice="software_delivery",
            expected_source_ids=("story",),
            expected_citations=(EvalCitationLabel("story", "user_story", 0),),
        ),
    )


def _observations_for(cases: Sequence[EvalCase]) -> dict[str, RagObservation]:
    mapping: dict[str, RagObservation] = {}
    for case in cases:
        if case.kind != "ask":
            continue
        ids = tuple(case.expected_source_ids or ())
        hits = tuple(_hit(item) for item in ids)
        citations = tuple(_citation(item) for item in ids)
        if case.case_class == "unknown_source_kind":
            hits = (_hit("w", source_type="future-connector"),)
            citations = (_citation("w", source_type="future-connector"),)
        if case.case_class == "irrelevant":
            hits = ()
            citations = ()
        if case.id == "sd":
            hits = (_hit("story", source_type="user_story"),)
            citations = (_citation("story", source_type="user_story"),)
        mapping[case.id] = _observation(case, hits, citations)
    return mapping


def _execute(
    cases: Sequence[EvalCase],
    *,
    judge: object | None = None,
    baseline: RagJudgeBaseline | None = None,
    execution_mode: str = "live",
    observations: Mapping[str, RagObservation] | None = None,
):
    return EvaluateRag().execute(
        cases,
        observations if observations is not None else _observations_for(cases),
        judge if judge is not None else _ScriptedJudge(),
        RagJudgeThresholds(),
        baseline if baseline is not None else _baseline(),
        _judge_meta(),
        _answer_meta(),
        _fingerprints(),
        execution_mode=execution_mode,
        judge_settings={"temperature": 0},
    )


def test_evaluate_rag_ignores_non_ask_cases() -> None:
    retrieve = EvalCase(
        id="r1",
        case_class="single_source",
        kind="retrieve",
        query="q",
        k=5,
        expected_source_ids=("doc-a",),
    )
    pack = EvalCase(
        id="p1",
        case_class="pack_off",
        kind="pack_off",
        query="assess the risk of checkout",
        k=5,
    )
    tool = EvalCase(
        id="t1",
        case_class="tool",
        kind="invoke_tool",
        tool_name="software_delivery.risk_score",
        arguments={"target": "x"},
        expected_tool_result={"level": "high"},
    )
    judge = _ScriptedJudge()
    report = _execute(_coverage_cases() + (retrieve, pack, tool), judge=judge)

    assert {item.case_id for item in report.results} == {
        "cross", "irr", "conf", "unk", "cite", "sd"
    }
    assert len(judge.calls) == 6 * 5


def test_valid_judge_json_is_scored() -> None:
    result = parse_judge_output(
        "faithfulness", '{"score": 0.75, "explanation": "grounded"}'
    )
    assert result.status == "scored"
    assert result.score == 0.75
    assert result.explanation == "grounded"
    assert result.error_type is None


def test_malformed_and_non_finite_scores_are_judge_failures() -> None:
    assert parse_judge_output("faithfulness", "not-json").error_type == "invalid_json"
    assert parse_judge_output("faithfulness", "true").error_type == "invalid_json"
    assert parse_judge_output(
        "faithfulness", '{"score": true, "explanation": "x"}'
    ).error_type == "invalid_score"
    assert parse_judge_output(
        "faithfulness", '{"score": NaN, "explanation": "x"}'
    ).error_type == "invalid_score"
    assert parse_judge_output(
        "faithfulness", '{"score": 1.5, "explanation": "x"}'
    ).error_type == "invalid_score"
    assert parse_judge_output(
        "faithfulness", '{"score": 0.2}'
    ).error_type == "invalid_json"
    failed = parse_judge_output("faithfulness", '{"score": true, "explanation": "x"}')
    assert failed.status == "judge_failure"
    assert failed.score is None


def test_provider_error_is_sanitized_judge_failure() -> None:
    class _Boom:
        def complete(self, system, messages, settings):
            raise ProviderError("The OpenRouter chat provider could not be reached.")

    cases = _coverage_cases()
    report = _execute(cases, judge=_Boom())
    first = report.results[0].metrics["context_relevance"]
    assert first.status == "judge_failure"
    assert first.score is None
    assert first.error_type == "provider_error"
    assert report.quality_gate_passed is False


def test_retrieval_and_citation_misses_and_unknown_types() -> None:
    case = _ask_case(
        "cite",
        case_class="citation_provenance",
        expected_source_ids=("doc-a", "doc-b"),
        expected_citations=(
            EvalCitationLabel("doc-a", "knowledge_document"),
            EvalCitationLabel("doc-b", "knowledge_document"),
        ),
    )
    observation = _observation(
        case,
        (_hit("doc-a"), _hit("ghost", source_type="future-connector")),
        (),
    )
    cases = tuple(item for item in _coverage_cases() if item.id != "cite") + (case,)
    report = _execute(
        cases,
        observations={**_observations_for(cases), "cite": observation},
    )
    result = next(item for item in report.results if item.case_id == "cite")
    assert result.retrieved_source_misses == ("doc-b",)
    assert result.citation_source_misses == ("doc-a",)
    assert "future-connector" in result.unknown_source_types
    assert "retrieval_source_miss" in result.failure_categories
    assert "citation_source_miss" in result.failure_categories
    assert "unknown_source_type" in result.failure_categories


def test_mean_uses_scored_only_pass_rate_uses_all_eligible() -> None:
    class _Mixed:
        def __init__(self) -> None:
            self.n = 0

        def complete(self, system, messages, settings):
            self.n += 1
            if self.n <= 5:
                return AskResult(content="not-json", model="j")
            return AskResult(
                content='{"score": 1.0, "explanation": "ok"}', model="j"
            )

    report = _execute(_coverage_cases(), judge=_Mixed())
    aggregate = report.aggregates["context_relevance"]
    assert aggregate.eligible_count == 6
    assert aggregate.scored_count == 5
    assert aggregate.mean == 1.0
    assert aggregate.pass_rate == 5 / 6


def test_unaccepted_baseline_refuses_gate() -> None:
    report = _execute(_coverage_cases(), baseline=_baseline(accepted=False))
    assert report.quality_gate_eligible is False
    assert report.quality_gate_passed is False
    assert report.gate_status == "refused_baseline"
    assert report.baseline_comparison == "unaccepted"


def test_incompatible_baseline_refuses_gate() -> None:
    other = RagJudgeFingerprints(
        dataset_hash="e" * 64,
        corpus_hash="c" * 64,
        metric_set=METRIC_IDS,
        judge_provider="openrouter",
        judge_model="judge-model",
        prompt_version=PROMPT_VERSION,
        answer_provider="openrouter",
        answer_model="answer-model",
        embedding_model="embed-model",
        retrieval_limit=5,
        relevance_threshold=0.0,
        hybrid_enabled=True,
        hybrid_alpha=0.5,
        rewriter="openrouter-rewrite",
    )
    baseline = RagJudgeBaseline(
        accepted=True,
        means={name: 0.9 for name in METRIC_IDS},
        fingerprints=other,
        allowed_drop=0.05,
    )
    report = _execute(_coverage_cases(), baseline=baseline)
    assert report.gate_status == "refused_baseline"
    assert report.baseline_comparison == "incompatible"
    assert report.quality_gate_eligible is False


def test_fake_mode_is_never_quality_eligible() -> None:
    report = _execute(_coverage_cases(), execution_mode="fake")
    assert report.execution_mode == "fake"
    assert report.quality_gate_eligible is False
    assert report.quality_gate_passed is False
    assert report.results[0].error_type == "fake_ineligible"


def test_csv_headers_are_stable() -> None:
    report = _execute(_coverage_cases())
    csv_text = rag_judge_report_to_csv(report)
    header = csv_text.splitlines()[0]
    assert header.split(",") == list(CSV_HEADERS)
