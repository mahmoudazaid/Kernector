"""Shared Judge fixtures for eval application, CLI, and composition tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from application.contracts import Citation, RunMeta
from application.evaluate_rag import EvaluateRag
from application.evaluation_contracts import EvalCase, EvalCitationLabel
from application.observed_rag import AnswerModelMetadata, RagObservation
from application.rag_judge_contracts import (
    AnswerRunMetadata,
    JudgeMetadata,
    RagJudgeBaseline,
    RagJudgeFingerprints,
    RagJudgeThresholds,
)
from application.rag_judge_policy import METRIC_IDS, PROMPT_VERSION
from domain.knowledge import DocumentChunk, ScoredChunk, SourceMetadata, SourceReference
from domain.models import AskResult

_UNSET = object()


def hit(source_id: str, *, source_type: str = "knowledge_document") -> ScoredChunk:
    """Build a scored chunk for Judge fixtures."""
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(SourceReference(source_id, source_type)),
            index=0,
            content="chunk",
        ),
        score=1.0,
    )


def citation(source_id: str, *, source_type: str = "knowledge_document") -> Citation:
    """Build a citation for Judge fixtures."""
    return Citation(SourceReference(source_id, source_type), quote="chunk", chunk_index=0)


def fingerprints() -> RagJudgeFingerprints:
    """Compatible fingerprints for an accepted baseline and live report."""
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


def fingerprint_payload() -> dict[str, object]:
    """JSON-shaped fingerprint mapping matching :func:`fingerprints`."""
    item = fingerprints()
    return {
        "dataset_hash": item.dataset_hash,
        "corpus_hash": item.corpus_hash,
        "metric_set": list(item.metric_set),
        "judge_provider": item.judge_provider,
        "judge_model": item.judge_model,
        "prompt_version": item.prompt_version,
        "answer_provider": item.answer_provider,
        "answer_model": item.answer_model,
        "embedding_model": item.embedding_model,
        "retrieval_limit": item.retrieval_limit,
        "relevance_threshold": item.relevance_threshold,
        "hybrid_enabled": item.hybrid_enabled,
        "hybrid_alpha": item.hybrid_alpha,
        "rewriter": item.rewriter,
    }


def judge_meta() -> JudgeMetadata:
    """Judge identity used by fixture reports."""
    return JudgeMetadata(
        provider="openrouter",
        model="judge-model",
        prompt_version=PROMPT_VERSION,
        temperature=0,
    )


def answer_meta() -> AnswerRunMetadata:
    """Answer-model identity used by fixture reports."""
    return AnswerRunMetadata(provider="openrouter", model="answer-model")


def make_baseline(*, accepted: bool = True) -> RagJudgeBaseline:
    """Accepted (by default) baseline matching :func:`fingerprints`."""
    return RagJudgeBaseline(
        accepted=accepted,
        means={name: 0.9 for name in METRIC_IDS},
        fingerprints=fingerprints(),
        allowed_drop=0.05,
    )


def ask_case(
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
    """Build one ask EvalCase for Judge coverage fixtures."""
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


def observation(
    case: EvalCase, hits: Sequence[ScoredChunk], citations: Sequence[Citation]
) -> RagObservation:
    """Observation with confirmed shared retrieve hits for scored fixtures."""
    return RagObservation(
        case_id=case.id,
        query=case.query or "",
        answer="visible answer",
        citations=citations,
        retrieved_contexts=hits,
        run=RunMeta(outcome="success", hit_count=len(hits)),
        answer_model=AnswerModelMetadata(provider="openrouter", model="answer-model"),
        shared_retrieve_hits=True,
    )


class ScriptedJudge:
    """ChatModel double that returns fixed Judge JSON."""

    def __init__(self, content: str = '{"score": 0.8, "explanation": "ok"}') -> None:
        self.content = content
        self.calls: list[tuple[str, tuple, dict]] = []

    def complete(
        self, system: str, messages: Sequence[object], settings: Mapping[str, object]
    ) -> AskResult:
        self.calls.append((system, tuple(messages), dict(settings)))
        return AskResult(content=self.content, model="judge-model")


def coverage_cases() -> tuple[EvalCase, ...]:
    """Minimal ask suite covering required Judge classes and slice."""
    return (
        ask_case(
            "cross",
            case_class="cross_source",
            expected_source_ids=("a", "b"),
            expected_citations=(
                EvalCitationLabel("a", "knowledge_document"),
                EvalCitationLabel("b", "knowledge_document"),
            ),
        ),
        ask_case(
            "irr",
            case_class="irrelevant",
            expected_source_ids=None,
            expected_citations=(),
            expected_answer_mode="insufficient",
        ),
        ask_case(
            "conf",
            case_class="conflicting",
            expected_source_ids=("a", "b"),
            expected_citations=(
                EvalCitationLabel("a", "knowledge_document"),
                EvalCitationLabel("b", "knowledge_document"),
            ),
        ),
        ask_case(
            "unk",
            case_class="unknown_source_kind",
            expected_source_ids=("w",),
            expected_citations=(EvalCitationLabel("w", "future-connector", 0),),
        ),
        ask_case("cite", case_class="citation_provenance"),
        ask_case(
            "sd",
            case_class="citation_provenance",
            slice="software_delivery",
            expected_source_ids=("story",),
            expected_citations=(EvalCitationLabel("story", "user_story", 0),),
        ),
    )


def observations_for(cases: Sequence[EvalCase]) -> dict[str, RagObservation]:
    """Map ask case ids to matching observations."""
    mapping: dict[str, RagObservation] = {}
    for case in cases:
        if case.kind != "ask":
            continue
        ids = tuple(case.expected_source_ids or ())
        hits = tuple(hit(item) for item in ids)
        citations = tuple(citation(item) for item in ids)
        if case.case_class == "unknown_source_kind":
            hits = (hit("w", source_type="future-connector"),)
            citations = (citation("w", source_type="future-connector"),)
        if case.case_class == "irrelevant":
            hits = ()
            citations = ()
        if case.id == "sd":
            hits = (hit("story", source_type="user_story"),)
            citations = (citation("story", source_type="user_story"),)
        mapping[case.id] = observation(case, hits, citations)
    return mapping


def execute(
    cases: Sequence[EvalCase],
    *,
    judge: object | None = None,
    baseline: object = _UNSET,
    execution_mode: str = "live",
    observations: Mapping[str, RagObservation] | None = None,
    judge_settings: object = _UNSET,
    thresholds: RagJudgeThresholds | None = None,
    observation_errors: Mapping[str, str] | None = None,
):
    """Run ``EvaluateRag.execute`` with fixture defaults."""
    resolved_baseline = make_baseline() if baseline is _UNSET else baseline
    settings = {"temperature": 0} if judge_settings is _UNSET else judge_settings
    return EvaluateRag().execute(
        cases,
        observations if observations is not None else observations_for(cases),
        judge if judge is not None else ScriptedJudge(),
        thresholds if thresholds is not None else RagJudgeThresholds(),
        resolved_baseline,
        judge_meta(),
        answer_meta(),
        fingerprints(),
        execution_mode=execution_mode,
        judge_settings=settings,
        observation_errors=observation_errors,
    )


def scripted_judge(content: str = '{"score": 0.8, "explanation": "ok"}') -> ScriptedJudge:
    """Return a scripted Judge model for composition tests."""
    return ScriptedJudge(content)


def judge_report(*, eligible: bool, passed: bool):
    """Build a real EvaluateRag report for CLI exit-code tests.

    Args:
        eligible (bool): When false, return a fake ineligible report.
        passed (bool): When eligible, whether the live gate should pass.

    Returns:
        RagJudgeReport: Report produced by ``EvaluateRag.execute``.
    """
    if not eligible:
        return execute(coverage_cases(), execution_mode="fake", baseline=None)
    content = (
        '{"score": 1.0, "explanation": "ok"}'
        if passed
        else '{"score": 0.8, "explanation": "ok"}'
    )
    return execute(
        coverage_cases(),
        judge=ScriptedJudge(content),
        baseline=make_baseline(),
        execution_mode="live",
    )
