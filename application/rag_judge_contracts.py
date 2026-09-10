"""Typed contracts for RAG LLM-as-Judge reports, metrics, and baselines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite

from application.errors import ApplicationValidationError
from application.rag_judge_policy import (
    DEFAULT_ALLOWED_DROP,
    DEFAULT_METRIC_FLOOR,
    DEFAULT_PASS_RATE_FLOOR,
    METRIC_IDS,
    PROMPT_VERSION,
)

RAG_JUDGE_SCHEMA_VERSION = "kernector.rag-judge.v1"
RAG_JUDGE_BASELINE_SCHEMA_VERSION = "kernector.rag-judge-baseline.v1"
CSV_HEADERS: tuple[str, ...] = (
    "case_id",
    "slice",
    "case_class",
    "execution_mode",
    "quality_gate_eligible",
    "context_relevance_status",
    "context_relevance_score",
    "faithfulness_status",
    "faithfulness_score",
    "answer_correctness_status",
    "answer_correctness_score",
    "citation_accuracy_status",
    "citation_accuracy_score",
    "citation_completeness_status",
    "citation_completeness_score",
    "retrieved_source_misses",
    "citation_source_misses",
    "unknown_source_types",
    "failure_categories",
    "error_type",
)

_METRIC_STATUSES = frozenset({"scored", "judge_failure"})
_EXECUTION_MODES = frozenset({"live", "fake"})
_GATE_STATUSES = frozenset(
    {"passed", "failed", "ineligible", "refused_baseline"}
)
_ERROR_TYPES = frozenset(
    {
        "invalid_json",
        "invalid_score",
        "missing_score",
        "missing_explanation",
        "blank_explanation",
        "explanation_too_long",
        "payload_too_large",
        "provider_error",
        "judge_error",
        "observation_integrity",
        "fake_ineligible",
    }
)
OBSERVATION_ERROR_TYPES = frozenset({"observation_integrity", "judge_error"})
_SLICES = frozenset({"core", "software_delivery"})


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApplicationValidationError(
            f"{field_name} must be a non-empty string, got {type(value).__name__}"
        )
    return value


def _require_unit_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApplicationValidationError(
            f"{field_name} must be a finite number in [0, 1]"
        )
    number = float(value)
    if not isfinite(number) or number < 0.0 or number > 1.0:
        raise ApplicationValidationError(
            f"{field_name} must be a finite number in [0, 1]"
        )
    return number


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ApplicationValidationError(
            f"{field_name} must be a sequence, got {type(value).__name__}"
        )
    return value


@dataclass(frozen=True, slots=True)
class MetricResult:
    """One Judge metric outcome.

    Args:
        metric_id (str): Metric name.
        status (str): ``scored`` or ``judge_failure``.
        score (float | None): Finite score in ``[0, 1]`` when scored.
        explanation (str | None): Non-blank explanation when scored.
        error_type (str | None): Sanitized failure code only.
    """

    metric_id: str
    status: str
    score: float | None = None
    explanation: str | None = None
    error_type: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.metric_id, "metric_id")
        if self.metric_id not in METRIC_IDS:
            raise ApplicationValidationError(
                f"metric_id must be a known judge metric, got {self.metric_id}"
            )
        if self.status not in _METRIC_STATUSES:
            raise ApplicationValidationError(
                "status must be scored or judge_failure"
            )
        if self.status == "scored":
            if self.score is None or isinstance(self.score, bool):
                raise ApplicationValidationError(
                    "scored metrics require a finite score in [0, 1]"
                )
            if not isinstance(self.score, (int, float)) or not isfinite(float(self.score)):
                raise ApplicationValidationError(
                    "scored metrics require a finite score in [0, 1]"
                )
            if float(self.score) < 0.0 or float(self.score) > 1.0:
                raise ApplicationValidationError(
                    "scored metrics require a finite score in [0, 1]"
                )
            object.__setattr__(self, "score", float(self.score))
            _require_text(self.explanation, "explanation")
            if self.error_type is not None:
                raise ApplicationValidationError(
                    "error_type is only allowed when status is judge_failure"
                )
        else:
            if self.score is not None:
                raise ApplicationValidationError(
                    "judge_failure metrics must not set a score"
                )
            if self.error_type not in _ERROR_TYPES:
                raise ApplicationValidationError(
                    "judge_failure requires a sanitized error_type"
                )


@dataclass(frozen=True, slots=True)
class JudgeMetadata:
    """Sanitized Judge configuration as recorded on a report.

    Args:
        provider (str): Judge provider id.
        model (str): Judge model id.
        prompt_version (str): Prompt pack version.
        temperature (float): Requested temperature (always ``0``).
        seed_configured (int | None): Seed from env, if any.
        seed_applied (int | None): Seed actually sent, if the provider allows it.
    """

    provider: str
    model: str
    prompt_version: str
    temperature: float
    seed_configured: int | None = None
    seed_applied: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.provider, "provider")
        _require_text(self.model, "model")
        if self.prompt_version != PROMPT_VERSION:
            raise ApplicationValidationError(
                "prompt_version must be kernector.rag-judge.prompts.v1"
            )
        if isinstance(self.temperature, bool) or not isinstance(
            self.temperature, (int, float)
        ):
            raise ApplicationValidationError("temperature must be 0")
        if float(self.temperature) != 0.0:
            raise ApplicationValidationError("temperature must be 0")
        object.__setattr__(self, "temperature", 0.0)


@dataclass(frozen=True, slots=True)
class AnswerRunMetadata:
    """Sanitized answer-model identity for a Judge report."""

    provider: str
    model: str

    def __post_init__(self) -> None:
        _require_text(self.provider, "provider")
        _require_text(self.model, "model")


@dataclass(frozen=True, slots=True)
class RagJudgeFingerprints:
    """Compatibility key for baseline comparison.

    Args:
        dataset_hash (str): SHA-256 of the cases file.
        corpus_hash (str): SHA-256 of the corpus file.
        metric_set (Sequence[str]): Ordered metric ids.
        judge_provider (str): Judge provider.
        judge_model (str): Judge model.
        prompt_version (str): Prompt version.
        answer_provider (str): Answer provider.
        answer_model (str): Answer model.
        embedding_model (str): Embedding model id.
        retrieval_limit (int): Default retrieval limit.
        relevance_threshold (float): Relevance floor.
        hybrid_enabled (bool): Hybrid flag.
        hybrid_alpha (float): Hybrid alpha.
        rewriter (str): Rewriter identity.
    """

    dataset_hash: str
    corpus_hash: str
    metric_set: Sequence[str]
    judge_provider: str
    judge_model: str
    prompt_version: str
    answer_provider: str
    answer_model: str
    embedding_model: str
    retrieval_limit: int
    relevance_threshold: float
    hybrid_enabled: bool
    hybrid_alpha: float
    rewriter: str

    def __post_init__(self) -> None:
        for name in (
            "dataset_hash",
            "corpus_hash",
            "judge_provider",
            "judge_model",
            "answer_provider",
            "answer_model",
            "embedding_model",
            "rewriter",
        ):
            _require_text(getattr(self, name), name)
        if self.prompt_version != PROMPT_VERSION:
            raise ApplicationValidationError(
                "prompt_version must be kernector.rag-judge.prompts.v1"
            )
        metrics = _require_sequence(self.metric_set, "metric_set")
        copied = tuple(_require_text(item, "metric_set item") for item in metrics)
        if copied != METRIC_IDS:
            raise ApplicationValidationError("metric_set must be the five Judge metrics")
        object.__setattr__(self, "metric_set", copied)
        if (
            not isinstance(self.retrieval_limit, int)
            or isinstance(self.retrieval_limit, bool)
            or self.retrieval_limit <= 0
        ):
            raise ApplicationValidationError(
                "retrieval_limit must be a positive integer"
            )
        if not isinstance(self.hybrid_enabled, bool):
            raise ApplicationValidationError("hybrid_enabled must be a bool")
        for name in ("relevance_threshold", "hybrid_alpha"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ApplicationValidationError(f"{name} must be a finite number")
            number = float(value)
            if not isfinite(number):
                raise ApplicationValidationError(f"{name} must be a finite number")
            object.__setattr__(self, name, number)


@dataclass(frozen=True, slots=True)
class RagJudgeThresholds:
    """Documented floors and allowed regression drop.

    Args:
        metric_floor (float): Minimum mean per metric.
        pass_rate_floor (float): Minimum pass rate per metric.
        allowed_drop (float): Allowed drop from an accepted baseline mean.
    """

    metric_floor: float = DEFAULT_METRIC_FLOOR
    pass_rate_floor: float = DEFAULT_PASS_RATE_FLOOR
    allowed_drop: float = DEFAULT_ALLOWED_DROP

    def __post_init__(self) -> None:
        for name in ("metric_floor", "pass_rate_floor", "allowed_drop"):
            object.__setattr__(self, name, _require_unit_number(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class RagJudgeBaseline:
    """Stored means used as a regression reference.

    Args:
        accepted (bool): Whether this baseline may be used as a regression gate.
        means (Mapping[str, float]): Per-metric accepted means.
        fingerprints (RagJudgeFingerprints): Compatibility key.
        allowed_drop (float): Drop tolerance recorded with the baseline.
    """

    accepted: bool
    means: Mapping[str, float]
    fingerprints: RagJudgeFingerprints
    allowed_drop: float = DEFAULT_ALLOWED_DROP

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise ApplicationValidationError("accepted must be a bool")
        if not isinstance(self.fingerprints, RagJudgeFingerprints):
            raise ApplicationValidationError(
                "fingerprints must be a RagJudgeFingerprints"
            )
        if not isinstance(self.means, Mapping):
            raise ApplicationValidationError("means must be a mapping")
        copied: dict[str, float] = {}
        for key, value in self.means.items():
            _require_text(key, "means key")
            if key not in METRIC_IDS:
                raise ApplicationValidationError(f"unknown baseline metric {key}")
            copied[key] = _require_unit_number(value, f"means[{key}]")
        if set(copied) != set(METRIC_IDS):
            raise ApplicationValidationError(
                "baseline means must include exactly the five Judge metrics"
            )
        drop = _require_unit_number(self.allowed_drop, "allowed_drop")
        object.__setattr__(self, "means", copied)
        object.__setattr__(self, "allowed_drop", drop)


@dataclass(frozen=True, slots=True)
class MetricAggregate:
    """Mean over scored cases and pass rate over all eligible cases.

    Args:
        mean (float | None): Mean of scored values, or ``None`` when none scored.
        pass_rate (float): Passes / eligible count (``0.0`` when eligible is 0).
        scored_count (int): Cases with status ``scored``.
        eligible_count (int): All Judge-eligible cases.
    """

    mean: float | None
    pass_rate: float
    scored_count: int
    eligible_count: int

    def __post_init__(self) -> None:
        if self.mean is not None:
            if isinstance(self.mean, bool) or not isinstance(self.mean, (int, float)):
                raise ApplicationValidationError("mean must be a number or None")
            object.__setattr__(self, "mean", float(self.mean))
        object.__setattr__(self, "pass_rate", float(self.pass_rate))
        if self.scored_count < 0 or self.eligible_count < 0:
            raise ApplicationValidationError("counts must be non-negative")


@dataclass(frozen=True, slots=True)
class RagJudgeCaseResult:
    """Per-case Judge metrics plus deterministic diagnostics.

    Args:
        case_id (str): Case identifier.
        slice (str): ``core`` or ``software_delivery``.
        case_class (str): Coverage class.
        metrics (Mapping[str, MetricResult]): Five metric results.
        retrieved_source_misses (Sequence[str]): Expected sources absent from retrieval.
        citation_source_misses (Sequence[str]): Retrieved expected sources not cited.
        unknown_source_types (Sequence[str]): Source types outside the well-known set.
        failure_categories (Sequence[str]): Derived category codes.
        error_type (str | None): First sanitized Judge error, if any.
    """

    case_id: str
    slice: str
    case_class: str
    metrics: Mapping[str, MetricResult]
    retrieved_source_misses: Sequence[str]
    citation_source_misses: Sequence[str]
    unknown_source_types: Sequence[str]
    failure_categories: Sequence[str]
    error_type: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.case_id, "case_id")
        if self.slice not in _SLICES:
            raise ApplicationValidationError(
                "slice must be core or software_delivery"
            )
        _require_text(self.case_class, "case_class")
        if not isinstance(self.metrics, Mapping):
            raise ApplicationValidationError("metrics must be a mapping")
        copied: dict[str, MetricResult] = {}
        for key, value in self.metrics.items():
            if key not in METRIC_IDS or not isinstance(value, MetricResult):
                raise ApplicationValidationError(
                    "metrics must include MetricResult values"
                )
            copied[key] = value
        for required in METRIC_IDS:
            if required not in copied:
                raise ApplicationValidationError(
                    f"metrics missing required metric {required}"
                )
        object.__setattr__(self, "metrics", copied)
        object.__setattr__(
            self, "retrieved_source_misses", tuple(self.retrieved_source_misses)
        )
        object.__setattr__(
            self, "citation_source_misses", tuple(self.citation_source_misses)
        )
        object.__setattr__(
            self, "unknown_source_types", tuple(self.unknown_source_types)
        )
        object.__setattr__(self, "failure_categories", tuple(self.failure_categories))
        if self.error_type is not None and self.error_type not in _ERROR_TYPES:
            raise ApplicationValidationError("error_type must be a sanitized code")


@dataclass(frozen=True, slots=True)
class RagJudgeReport:
    """Additive RAG Judge report (``kernector.rag-judge.v1``).

    Args:
        schema_version (str): Literal schema id.
        execution_mode (str): ``live`` or ``fake``.
        quality_gate_eligible (bool): Whether this run may pass a quality gate.
        quality_gate_passed (bool): Whether the eligible gate passed.
        gate_status (str): ``passed``, ``failed``, ``ineligible``, or ``refused_baseline``.
        answer_model (AnswerRunMetadata): Answer-model identity.
        judge (JudgeMetadata): Sanitized Judge settings.
        fingerprints (RagJudgeFingerprints): Dataset and RAG fingerprints.
        results (Sequence[RagJudgeCaseResult]): Per eligible ask case.
        aggregates (Mapping[str, MetricAggregate]): Per-metric aggregates.
        limitations (Sequence[str]): Documented limitations.
        baseline_comparison (str | None): Comparison outcome code.
        allowed_drop (float): Effective regression drop used by the gate.
    """

    schema_version: str
    execution_mode: str
    quality_gate_eligible: bool
    quality_gate_passed: bool
    gate_status: str
    answer_model: AnswerRunMetadata
    judge: JudgeMetadata
    fingerprints: RagJudgeFingerprints
    results: Sequence[RagJudgeCaseResult]
    aggregates: Mapping[str, MetricAggregate]
    limitations: Sequence[str]
    baseline_comparison: str | None = None
    allowed_drop: float = DEFAULT_ALLOWED_DROP

    def __post_init__(self) -> None:
        if self.schema_version != RAG_JUDGE_SCHEMA_VERSION:
            raise ApplicationValidationError(
                "schema_version must be kernector.rag-judge.v1"
            )
        if self.execution_mode not in _EXECUTION_MODES:
            raise ApplicationValidationError("execution_mode must be live or fake")
        if self.gate_status not in _GATE_STATUSES:
            raise ApplicationValidationError("gate_status is invalid")
        if not isinstance(self.quality_gate_eligible, bool):
            raise ApplicationValidationError("quality_gate_eligible must be a bool")
        if not isinstance(self.quality_gate_passed, bool):
            raise ApplicationValidationError("quality_gate_passed must be a bool")
        if self.execution_mode == "fake" and self.quality_gate_eligible:
            raise ApplicationValidationError(
                "fake runs cannot be quality-gate eligible"
            )
        if self.quality_gate_passed and not self.quality_gate_eligible:
            raise ApplicationValidationError(
                "ineligible runs cannot pass the quality gate"
            )
        object.__setattr__(
            self, "allowed_drop", _require_unit_number(self.allowed_drop, "allowed_drop")
        )
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(self, "limitations", tuple(self.limitations))
        if not isinstance(self.aggregates, Mapping):
            raise ApplicationValidationError("aggregates must be a mapping")
        for required in METRIC_IDS:
            if required not in self.aggregates:
                raise ApplicationValidationError(
                    f"aggregates missing required metric {required}"
                )
