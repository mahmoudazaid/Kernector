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
    RAG_JUDGE_BASELINE_SCHEMA_VERSION,
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
    CASE_ERROR_TYPES,
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
        "story",
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
        observation_errors: Mapping[str, str] | None = None,
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
            observation_errors (Mapping[str, str] | None): Per-case error types
                when an observation is missing.

        Returns:
            RagJudgeReport: Additive Judge report. Incompatible or unaccepted
            baselines refuse the regression gate (``gate_status=refused_baseline``)
            rather than silently applying floors.
        """
        settings = dict(judge_settings) if judge_settings is not None else {
            "temperature": 0
        }
        missing_errors = {
            case_id: _observation_error_type(code)
            for case_id, code in (observation_errors or {}).items()
        }
        eligible = tuple(case for case in cases if case.kind == "ask")
        baseline_status = _baseline_status(execution_mode, baseline, fingerprints)
        results: list[RagJudgeCaseResult] = []
        for case in eligible:
            if execution_mode == "fake":
                results.append(_fake_case_result(case))
                continue
            observation = observations.get(case.id)
            if observation is None:
                results.append(
                    _failed_case(
                        case,
                        error_type=missing_errors.get(case.id, "judge_error"),
                    )
                )
                continue
            results.append(_score_case(case, observation, judge, settings))
        frozen = tuple(results)
        aggregates = _aggregates(frozen, thresholds)
        coverage_ok = _coverage_ok(eligible, frozen)
        gate_eligible, gate_passed, gate_status = _gate(
            execution_mode,
            baseline_status,
            frozen,
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
            results=frozen,
            aggregates=aggregates,
            limitations=_LIMITATIONS,
            baseline_comparison=baseline_status,
        )


def _baseline_status(
    execution_mode: str,
    baseline: RagJudgeBaseline | None,
    fingerprints: RagJudgeFingerprints,
) -> str:
    if execution_mode == "fake":
        return "not_compared"
    if baseline is None:
        return "not_compared"
    if not baseline.accepted:
        return "unaccepted"
    if not fingerprints_compatible(fingerprints, baseline.fingerprints):
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
        raw (str): Provider content. A fenced or extra-key JSON object is
            accepted when ``score`` and ``explanation`` are present.

    Returns:
        MetricResult: ``scored`` on valid JSON, else ``judge_failure`` with a
        sanitized ``error_type`` and ``score=None``.
    """
    try:
        payload = _extract_json_object(raw)
    except json.JSONDecodeError:
        return MetricResult(
            metric_id=metric_id, status="judge_failure", error_type="invalid_json"
        )
    if not isinstance(payload, dict):
        return MetricResult(
            metric_id=metric_id, status="judge_failure", error_type="invalid_json"
        )
    if "score" not in payload:
        return MetricResult(
            metric_id=metric_id, status="judge_failure", error_type="missing_score"
        )
    if "explanation" not in payload:
        return MetricResult(
            metric_id=metric_id,
            status="judge_failure",
            error_type="missing_explanation",
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


def _extract_json_object(raw: str) -> object:
    stripped = raw.strip()
    positions: list[int] = []
    index = 0
    while True:
        pos = stripped.find("```", index)
        if pos < 0:
            break
        positions.append(pos)
        index = pos + 3
    candidates: list[str] = []
    for close_index in range(len(positions) - 1, 0, -1):
        close = positions[close_index]
        for open_index in range(close_index - 1, -1, -1):
            body = stripped[positions[open_index] + 3 : close].strip()
            if body.lower().startswith("json"):
                rest = body[4:]
                if not rest or rest[0].isspace():
                    body = rest.lstrip()
            candidates.append(body)
    candidates.append(stripped)
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            return _verdict_object(candidate)
        except json.JSONDecodeError as error:
            last_error = error
    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("no judge verdict object", stripped, 0)


def _verdict_object(text: str) -> object:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    else:
        if isinstance(payload, dict):
            return payload
    decoder = json.JSONDecoder()
    scored: object | None = None
    for start in range(len(text) - 1, -1, -1):
        if text[start] != "{":
            continue
        try:
            candidate, _end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if not isinstance(candidate, dict):
            continue
        if "score" in candidate:
            return candidate
        if scored is None:
            scored = candidate
    if scored is not None:
        return scored
    raise json.JSONDecodeError("no judge verdict object", text, 0)


def _observation_error_type(code: object) -> str:
    if isinstance(code, str) and code in CASE_ERROR_TYPES:
        return code
    return "judge_error"


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


def _coverage_ok(
    eligible: Sequence[EvalCase], results: Sequence[RagJudgeCaseResult]
) -> bool:
    scored_ids = {
        item.case_id
        for item in results
        if any(metric.status == "scored" for metric in item.metrics.values())
    }
    scored_cases = tuple(case for case in eligible if case.id in scored_ids)
    classes = {case.case_class for case in scored_cases}
    if any(name not in classes for name in REQUIRED_JUDGE_CLASSES):
        return False
    return any(case.slice == REQUIRED_JUDGE_SLICE for case in scored_cases)


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
    if any(item.error_type == "observation_integrity" for item in results):
        return True, False, "failed"
    assert baseline is not None
    drop = min(thresholds.allowed_drop, baseline.allowed_drop)
    for metric_id, aggregate in aggregates.items():
        if aggregate.mean is None:
            return True, False, "failed"
        if aggregate.scored_count <= aggregate.eligible_count // 2:
            return True, False, "failed"
        if aggregate.mean < thresholds.metric_floor:
            return True, False, "failed"
        if aggregate.pass_rate < thresholds.pass_rate_floor:
            return True, False, "failed"
        floor = baseline.means[metric_id] - drop
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


_BASELINE_ROOT_KEYS = frozenset(
    {"schema_version", "accepted", "allowed_drop", "means", "fingerprints"}
)


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
    unknown = set(payload) - _BASELINE_ROOT_KEYS
    if unknown:
        raise ApplicationValidationError("rag judge baseline has unknown fields")
    if payload.get("schema_version") != RAG_JUDGE_BASELINE_SCHEMA_VERSION:
        raise ApplicationValidationError(
            "rag judge baseline schema_version is invalid"
        )
    fingerprints_raw = payload.get("fingerprints")
    if not isinstance(fingerprints_raw, Mapping):
        raise ApplicationValidationError("baseline fingerprints must be an object")
    means_raw = payload.get("means")
    if not isinstance(means_raw, Mapping):
        raise ApplicationValidationError("baseline means must be an object")
    accepted = payload.get("accepted")
    if not isinstance(accepted, bool):
        raise ApplicationValidationError("baseline accepted must be a bool")
    allowed = _baseline_number(payload, "allowed_drop", DEFAULT_ALLOWED_DROP)
    try:
        fingerprints = RagJudgeFingerprints(
            dataset_hash=_baseline_text(fingerprints_raw, "dataset_hash"),
            corpus_hash=_baseline_text(fingerprints_raw, "corpus_hash"),
            metric_set=_baseline_metric_set(fingerprints_raw),
            judge_provider=_baseline_text(fingerprints_raw, "judge_provider"),
            judge_model=_baseline_text(fingerprints_raw, "judge_model"),
            prompt_version=_baseline_text(fingerprints_raw, "prompt_version"),
            answer_provider=_baseline_text(fingerprints_raw, "answer_provider"),
            answer_model=_baseline_text(fingerprints_raw, "answer_model"),
            embedding_model=_baseline_text(fingerprints_raw, "embedding_model"),
            retrieval_limit=_baseline_int(fingerprints_raw, "retrieval_limit"),
            relevance_threshold=_baseline_number(
                fingerprints_raw, "relevance_threshold"
            ),
            hybrid_enabled=_baseline_bool(fingerprints_raw, "hybrid_enabled"),
            hybrid_alpha=_baseline_number(fingerprints_raw, "hybrid_alpha"),
            rewriter=_baseline_text(fingerprints_raw, "rewriter"),
        )
    except (KeyError, TypeError, ValueError, ApplicationValidationError) as error:
        raise ApplicationValidationError(
            "rag judge baseline fingerprints are invalid"
        ) from error
    try:
        means = {str(key): value for key, value in means_raw.items()}
        return RagJudgeBaseline(
            accepted=accepted,
            means=means,
            fingerprints=fingerprints,
            allowed_drop=allowed,
        )
    except (TypeError, ValueError, ApplicationValidationError) as error:
        raise ApplicationValidationError("rag judge baseline is invalid") from error


def _baseline_text(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApplicationValidationError(f"baseline fingerprints.{key} is invalid")
    return value


def _baseline_bool(raw: Mapping[str, object], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ApplicationValidationError(f"baseline fingerprints.{key} is invalid")
    return value


def _baseline_int(raw: Mapping[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApplicationValidationError(f"baseline fingerprints.{key} is invalid")
    return value


def _baseline_number(
    raw: Mapping[str, object], key: str, default: float | None = None
) -> float:
    if key not in raw:
        if default is None:
            raise ApplicationValidationError(f"baseline {key} is invalid")
        return float(default)
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApplicationValidationError(f"baseline {key} is invalid")
    number = float(value)
    if not isfinite(number):
        raise ApplicationValidationError(f"baseline {key} is invalid")
    return number


def _baseline_metric_set(raw: Mapping[str, object]) -> tuple[str, ...]:
    value = raw.get("metric_set")
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ApplicationValidationError("baseline fingerprints.metric_set is invalid")
    return tuple(str(item) for item in value)


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
