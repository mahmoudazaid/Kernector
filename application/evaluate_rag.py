"""Score Judge-eligible ask observations with a ChatModel Judge."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
from io import StringIO
import json
from math import isfinite

from application.errors import ApplicationValidationError
from application.evaluation_contracts import EvalCase
from application.observed_rag import RagObservation
from application.rag_judge_contracts import (
    CSV_HEADERS,
    RAG_JUDGE_SCHEMA_VERSION,
    AnswerRunMetadata,
    JudgeMetadata,
    MetricAggregate,
    MetricResult,
    RagJudgeBaseline,
    RagJudgeCaseResult,
    RagJudgeFingerprints,
    RagJudgeReport,
    RagJudgeThresholds,
)
from application.rag_judge_policy import (
    DEFAULT_ALLOWED_DROP,
    MAX_EXPLANATION_CHARS,
    METRIC_IDS,
    REQUIRED_JUDGE_CLASSES,
    REQUIRED_JUDGE_SLICE,
    JudgePayloadTooLargeError,
    build_metric_messages,
)
from domain.errors import ProviderError
from domain.knowledge import SourceType
from domain.ports import ChatModel

_WELL_KNOWN_SOURCE_TYPES = frozenset(
    {
        SourceType.KNOWLEDGE_DOCUMENT,
        SourceType.GOOGLE_DRIVE,
        "user_story",
        "srs",
        "test",
    }
)

_LIMITATIONS: tuple[str, ...] = (
    "Judge scores are model opinions, not ground truth.",
    "Answer model and Judge model are distinct; never conflate them.",
    "kind=retrieve, pack_off, and invoke_tool are never Judged.",
    "Oversized Judge payloads are rejected, never truncated and scored.",
)


class BaselineIncompatibleError(ApplicationValidationError):
    """Supplied baseline cannot be used as a regression gate."""


def fingerprints_compatible(
    left: RagJudgeFingerprints, right: RagJudgeFingerprints
) -> bool:
    """Return whether two fingerprint records may be compared.

    Args:
        left (RagJudgeFingerprints): Run fingerprints.
        right (RagJudgeFingerprints): Baseline fingerprints.

    Returns:
        bool: True when every compatibility field matches.
    """
    return left == right


class EvaluateRag:
    """Judge only ``kind=ask`` observations with one ChatModel call per metric."""

    def execute(
        self,
        cases: Sequence[EvalCase],
        observations: Mapping[str, RagObservation],
        judge: ChatModel,
        thresholds: RagJudgeThresholds,
        baseline: RagJudgeBaseline | None,
        judge_meta: JudgeMetadata,
        answer_meta: AnswerRunMetadata,
        fingerprints: RagJudgeFingerprints,
        *,
        execution_mode: str = "live",
        judge_settings: Mapping[str, object] | None = None,
    ) -> RagJudgeReport:
        """Score eligible ask cases and aggregate a Judge report.

        Args:
            cases (Sequence[EvalCase]): Suite cases; non-ask kinds are ignored.
            observations (Mapping[str, RagObservation]): Same-run observations by id.
            judge (ChatModel): Judge model. Unused when ``execution_mode`` is fake.
            thresholds (RagJudgeThresholds): Floors and allowed drop.
            baseline (RagJudgeBaseline | None): Optional regression reference.
            judge_meta (JudgeMetadata): Sanitized Judge settings.
            answer_meta (AnswerRunMetadata): Answer-model identity.
            fingerprints (RagJudgeFingerprints): Dataset and RAG fingerprints.
            execution_mode (str): ``live`` or ``fake``.
            judge_settings (Mapping[str, object] | None): Settings sent to complete.

        Returns:
            RagJudgeReport: Additive Judge report. Incompatible or unaccepted
            baselines refuse the regression gate (``gate_status=refused_baseline``)
            rather than silently applying floors.
        """
        settings = dict(judge_settings or {"temperature": 0})
        eligible = tuple(case for case in cases if case.kind == "ask")
        baseline_status = _baseline_status(
            execution_mode, baseline, fingerprints, thresholds
        )
        results: list[RagJudgeCaseResult] = []
        for case in eligible:
            if execution_mode == "fake":
                results.append(_fake_case_result(case))
                continue
            observation = observations.get(case.id)
            if observation is None:
                results.append(_failed_case(case, error_type="judge_error"))
                continue
            results.append(_score_case(case, observation, judge, settings))
        aggregates = _aggregates(tuple(results), thresholds)
        coverage_ok = _coverage_ok(eligible)
        gate_eligible, gate_passed, gate_status = _gate(
            execution_mode,
            baseline_status,
            tuple(results),
            aggregates,
            thresholds,
            baseline,
            coverage_ok,
        )
        return RagJudgeReport(
            schema_version=RAG_JUDGE_SCHEMA_VERSION,
            execution_mode=execution_mode,
            quality_gate_eligible=gate_eligible,
            quality_gate_passed=gate_passed,
            gate_status=gate_status,
            answer_model=answer_meta,
            judge=judge_meta,
            fingerprints=fingerprints,
            results=tuple(results),
            aggregates=aggregates,
            limitations=_LIMITATIONS,
            baseline_comparison=baseline_status,
        )


def _baseline_status(
    execution_mode: str,
    baseline: RagJudgeBaseline | None,
    fingerprints: RagJudgeFingerprints,
    thresholds: RagJudgeThresholds,
) -> str:
    if execution_mode == "fake":
        return "not_compared"
    if baseline is None or not baseline.accepted:
        return "unaccepted"
    if not fingerprints_compatible(fingerprints, baseline.fingerprints):
        return "incompatible"
    if abs(baseline.allowed_drop - thresholds.allowed_drop) > 1e-12:
        return "incompatible"
    return "compared"


def _score_case(
    case: EvalCase,
    observation: RagObservation,
    judge: ChatModel,
    settings: Mapping[str, object],
) -> RagJudgeCaseResult:
    metrics: dict[str, MetricResult] = {}
    first_error: str | None = None
    for metric_id in METRIC_IDS:
        result = _score_metric(metric_id, case, observation, judge, settings)
        metrics[metric_id] = result
        if result.status == "judge_failure" and first_error is None:
            first_error = result.error_type
    retrieved_misses, citation_misses, unknown_types = _diagnostics(case, observation)
    return RagJudgeCaseResult(
        case_id=case.id,
        slice=case.slice,
        case_class=case.case_class,
        metrics=metrics,
        retrieved_source_misses=retrieved_misses,
        citation_source_misses=citation_misses,
        unknown_source_types=unknown_types,
        failure_categories=_failure_categories(
            metrics, retrieved_misses, citation_misses, unknown_types
        ),
        error_type=first_error,
    )


def _score_metric(
    metric_id: str,
    case: EvalCase,
    observation: RagObservation,
    judge: ChatModel,
    settings: Mapping[str, object],
) -> MetricResult:
    try:
        system, messages = build_metric_messages(metric_id, case, observation)
    except JudgePayloadTooLargeError:
        return MetricResult(
            metric_id=metric_id,
            status="judge_failure",
            error_type="payload_too_large",
        )
    try:
        completion = judge.complete(system, messages, settings)
    except ProviderError:
        return MetricResult(
            metric_id=metric_id,
            status="judge_failure",
            error_type="provider_error",
        )
    except Exception:
        return MetricResult(
            metric_id=metric_id,
            status="judge_failure",
            error_type="judge_error",
        )
    return parse_judge_output(metric_id, completion.content)


def parse_judge_output(metric_id: str, raw: str) -> MetricResult:
    """Parse a Judge completion into a MetricResult.

    Args:
        metric_id (str): Metric being scored.
        raw (str): Provider content.

    Returns:
        MetricResult: ``scored`` on valid JSON, else ``judge_failure`` with a
        sanitized ``error_type`` and ``score=None``.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return MetricResult(
            metric_id=metric_id, status="judge_failure", error_type="invalid_json"
        )
    if not isinstance(payload, dict) or set(payload) != {"score", "explanation"}:
        return MetricResult(
            metric_id=metric_id, status="judge_failure", error_type="invalid_json"
        )
    score = payload["score"]
    explanation = payload["explanation"]
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return MetricResult(
            metric_id=metric_id, status="judge_failure", error_type="invalid_score"
        )
    value = float(score)
    if not isfinite(value) or value < 0.0 or value > 1.0:
        return MetricResult(
            metric_id=metric_id, status="judge_failure", error_type="invalid_score"
        )
    if not isinstance(explanation, str):
        return MetricResult(
            metric_id=metric_id,
            status="judge_failure",
            error_type="missing_explanation",
        )
    if not explanation.strip():
        return MetricResult(
            metric_id=metric_id,
            status="judge_failure",
            error_type="blank_explanation",
        )
    if len(explanation) > MAX_EXPLANATION_CHARS:
        return MetricResult(
            metric_id=metric_id,
            status="judge_failure",
            error_type="explanation_too_long",
        )
    return MetricResult(
        metric_id=metric_id,
        status="scored",
        score=value,
        explanation=explanation,
    )


def _diagnostics(
    case: EvalCase, observation: RagObservation
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    expected = tuple(case.expected_source_ids or ())
    retrieved = {
        hit.chunk.reference.source_id for hit in observation.retrieved_contexts
    }
    cited = {item.reference.source_id for item in observation.citations}
    retrieved_misses = tuple(item for item in expected if item not in retrieved)
    citation_misses = tuple(
        item for item in expected if item in retrieved and item not in cited
    )
    types: list[str] = []
    seen: set[str] = set()
    for hit in observation.retrieved_contexts:
        source_type = hit.chunk.reference.source_type
        if source_type not in _WELL_KNOWN_SOURCE_TYPES and source_type not in seen:
            types.append(source_type)
            seen.add(source_type)
    for citation in observation.citations:
        source_type = citation.reference.source_type
        if source_type not in _WELL_KNOWN_SOURCE_TYPES and source_type not in seen:
            types.append(source_type)
            seen.add(source_type)
    return retrieved_misses, citation_misses, tuple(types)


def _failure_categories(
    metrics: Mapping[str, MetricResult],
    retrieved_misses: Sequence[str],
    citation_misses: Sequence[str],
    unknown_types: Sequence[str],
) -> tuple[str, ...]:
    categories: list[str] = []
    if retrieved_misses:
        categories.append("retrieval_source_miss")
    if citation_misses:
        categories.append("citation_source_miss")
    if unknown_types:
        categories.append("unknown_source_type")
    if any(item.status == "judge_failure" for item in metrics.values()):
        categories.append("judge_failure")
    return tuple(categories)


def _aggregates(
    results: Sequence[RagJudgeCaseResult], thresholds: RagJudgeThresholds
) -> dict[str, MetricAggregate]:
    eligible = len(results)
    aggregates: dict[str, MetricAggregate] = {}
    for metric_id in METRIC_IDS:
        scored = [
            item.metrics[metric_id]
            for item in results
            if item.metrics[metric_id].status == "scored"
        ]
        scores = [float(item.score) for item in scored if item.score is not None]
        mean = (sum(scores) / len(scores)) if scores else None
        passes = sum(1 for value in scores if value >= thresholds.metric_floor)
        pass_rate = (passes / eligible) if eligible else 0.0
        aggregates[metric_id] = MetricAggregate(
            mean=mean,
            pass_rate=pass_rate,
            scored_count=len(scores),
            eligible_count=eligible,
        )
    return aggregates


def _coverage_ok(eligible: Sequence[EvalCase]) -> bool:
    classes = {case.case_class for case in eligible}
    if any(name not in classes for name in REQUIRED_JUDGE_CLASSES):
        return False
    return any(case.slice == REQUIRED_JUDGE_SLICE for case in eligible)


def _gate(
    execution_mode: str,
    baseline_status: str,
    results: Sequence[RagJudgeCaseResult],
    aggregates: Mapping[str, MetricAggregate],
    thresholds: RagJudgeThresholds,
    baseline: RagJudgeBaseline | None,
    coverage_ok: bool,
) -> tuple[bool, bool, str]:
    if execution_mode == "fake":
        return False, False, "ineligible"
    if baseline_status != "compared":
        return False, False, "refused_baseline"
    if not results or not coverage_ok:
        return True, False, "failed"
    if any(item.error_type is not None for item in results):
        return True, False, "failed"
    for metric_id, aggregate in aggregates.items():
        if aggregate.mean is None:
            return True, False, "failed"
        if aggregate.mean < thresholds.metric_floor:
            return True, False, "failed"
        if aggregate.pass_rate < thresholds.pass_rate_floor:
            return True, False, "failed"
        if baseline is not None and metric_id in baseline.means:
            floor = baseline.means[metric_id] - thresholds.allowed_drop
            if aggregate.mean < floor:
                return True, False, "failed"
    return True, True, "passed"


def _fake_case_result(case: EvalCase) -> RagJudgeCaseResult:
    metrics = {
        metric_id: MetricResult(
            metric_id=metric_id,
            status="judge_failure",
            error_type="fake_ineligible",
        )
        for metric_id in METRIC_IDS
    }
    return RagJudgeCaseResult(
        case_id=case.id,
        slice=case.slice,
        case_class=case.case_class,
        metrics=metrics,
        retrieved_source_misses=(),
        citation_source_misses=(),
        unknown_source_types=(),
        failure_categories=("judge_failure",),
        error_type="fake_ineligible",
    )


def _failed_case(case: EvalCase, *, error_type: str) -> RagJudgeCaseResult:
    metrics = {
        metric_id: MetricResult(
            metric_id=metric_id, status="judge_failure", error_type=error_type
        )
        for metric_id in METRIC_IDS
    }
    return RagJudgeCaseResult(
        case_id=case.id,
        slice=case.slice,
        case_class=case.case_class,
        metrics=metrics,
        retrieved_source_misses=(),
        citation_source_misses=(),
        unknown_source_types=(),
        failure_categories=("judge_failure",),
        error_type=error_type,
    )


def rag_judge_report_to_dict(report: RagJudgeReport) -> dict[str, object]:
    """Convert ``report`` to a JSON-compatible mapping.

    Args:
        report (RagJudgeReport): Validated Judge report.

    Returns:
        dict[str, object]: Nested JSON-compatible structure.
    """
    return {
        "schema_version": report.schema_version,
        "execution_mode": report.execution_mode,
        "quality_gate_eligible": report.quality_gate_eligible,
        "quality_gate_passed": report.quality_gate_passed,
        "gate_status": report.gate_status,
        "baseline_comparison": report.baseline_comparison,
        "answer_model": {
            "provider": report.answer_model.provider,
            "model": report.answer_model.model,
        },
        "judge": {
            "provider": report.judge.provider,
            "model": report.judge.model,
            "prompt_version": report.judge.prompt_version,
            "temperature": report.judge.temperature,
            "seed_configured": report.judge.seed_configured,
            "seed_applied": report.judge.seed_applied,
        },
        "fingerprints": _fingerprints_to_dict(report.fingerprints),
        "aggregates": {
            name: {
                "mean": item.mean,
                "pass_rate": item.pass_rate,
                "scored_count": item.scored_count,
                "eligible_count": item.eligible_count,
            }
            for name, item in report.aggregates.items()
        },
        "limitations": list(report.limitations),
        "results": [_case_to_dict(item) for item in report.results],
    }


def _fingerprints_to_dict(item: RagJudgeFingerprints) -> dict[str, object]:
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


def _case_to_dict(item: RagJudgeCaseResult) -> dict[str, object]:
    return {
        "case_id": item.case_id,
        "slice": item.slice,
        "case_class": item.case_class,
        "metrics": {
            name: {
                "status": metric.status,
                "score": metric.score,
                "explanation": metric.explanation,
                "error_type": metric.error_type,
            }
            for name, metric in item.metrics.items()
        },
        "retrieved_source_misses": list(item.retrieved_source_misses),
        "citation_source_misses": list(item.citation_source_misses),
        "unknown_source_types": list(item.unknown_source_types),
        "failure_categories": list(item.failure_categories),
        "error_type": item.error_type,
    }


def parse_rag_judge_baseline(payload: Mapping[str, object]) -> RagJudgeBaseline:
    """Decode a committed baseline object.

    Args:
        payload (Mapping[str, object]): JSON object from the baseline file.

    Returns:
        RagJudgeBaseline: Validated baseline. ``accepted`` may be false.

    Raises:
        ApplicationValidationError: Missing or invalid fields.
    """
    if not isinstance(payload, Mapping):
        raise ApplicationValidationError("baseline root must be an object")
    fingerprints_raw = payload.get("fingerprints")
    if not isinstance(fingerprints_raw, Mapping):
        raise ApplicationValidationError("baseline fingerprints must be an object")
    means_raw = payload.get("means")
    if not isinstance(means_raw, Mapping):
        raise ApplicationValidationError("baseline means must be an object")
    allowed = payload.get("allowed_drop", DEFAULT_ALLOWED_DROP)
    accepted = payload.get("accepted")
    if not isinstance(accepted, bool):
        raise ApplicationValidationError("baseline accepted must be a bool")
    return RagJudgeBaseline(
        accepted=accepted,
        means={str(key): value for key, value in means_raw.items()},
        fingerprints=RagJudgeFingerprints(
            dataset_hash=str(fingerprints_raw["dataset_hash"]),
            corpus_hash=str(fingerprints_raw["corpus_hash"]),
            metric_set=tuple(fingerprints_raw["metric_set"]),
            judge_provider=str(fingerprints_raw["judge_provider"]),
            judge_model=str(fingerprints_raw["judge_model"]),
            prompt_version=str(fingerprints_raw["prompt_version"]),
            answer_provider=str(fingerprints_raw["answer_provider"]),
            answer_model=str(fingerprints_raw["answer_model"]),
            embedding_model=str(fingerprints_raw["embedding_model"]),
            retrieval_limit=int(fingerprints_raw["retrieval_limit"]),
            relevance_threshold=float(fingerprints_raw["relevance_threshold"]),
            hybrid_enabled=bool(fingerprints_raw["hybrid_enabled"]),
            hybrid_alpha=float(fingerprints_raw["hybrid_alpha"]),
            rewriter=str(fingerprints_raw["rewriter"]),
        ),
        allowed_drop=float(allowed),
    )


def rag_judge_report_to_json(report: RagJudgeReport) -> str:
    """Serialize ``report`` to deterministic JSON.

    Args:
        report (RagJudgeReport): Validated Judge report.

    Returns:
        str: JSON text with sorted keys and a trailing newline.
    """
    return json.dumps(rag_judge_report_to_dict(report), indent=2, sort_keys=True) + "\n"


def rag_judge_report_to_csv(report: RagJudgeReport) -> str:
    """Serialize ``report`` to CSV with stable headers.

    Args:
        report (RagJudgeReport): Validated Judge report.

    Returns:
        str: CSV text including a header row.
    """
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_HEADERS), lineterminator="\n")
    writer.writeheader()
    eligible = "true" if report.quality_gate_eligible else "false"
    for item in report.results:
        row: dict[str, object] = {
            "case_id": item.case_id,
            "slice": item.slice,
            "case_class": item.case_class,
            "execution_mode": report.execution_mode,
            "quality_gate_eligible": eligible,
            "retrieved_source_misses": "|".join(item.retrieved_source_misses),
            "citation_source_misses": "|".join(item.citation_source_misses),
            "unknown_source_types": "|".join(item.unknown_source_types),
            "failure_categories": "|".join(item.failure_categories),
            "error_type": item.error_type or "",
        }
        for metric_id in METRIC_IDS:
            metric = item.metrics[metric_id]
            row[f"{metric_id}_status"] = metric.status
            row[f"{metric_id}_score"] = "" if metric.score is None else metric.score
        writer.writerow(row)
    return buffer.getvalue()
