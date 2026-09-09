"""Typed contracts for the offline RAG and tool eval harness."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json

from application.errors import ApplicationValidationError

EVAL_SCHEMA_VERSION = "kernector.eval.v1"
EVAL_MODE_OFFLINE = "offline"

REQUIRED_CASE_CLASSES: tuple[str, ...] = (
    "single_source",
    "cross_source",
    "irrelevant",
    "conflicting",
    "unknown_source_kind",
    "citation_provenance",
    "pack_off",
    "tool",
)

REQUIRED_AGGREGATES: tuple[str, ...] = (
    "hit_at_k",
    "mrr",
    "source_recall_at_k",
)

_KINDS = frozenset({"retrieve", "ask", "invoke_tool", "pack_off"})
_ANSWER_MODES = frozenset({"grounded", "insufficient"})
_RESULT_STATUSES = frozenset({"pass", "fail", "skip"})
_COVERAGE_STATES = frozenset({"exercised", "skipped"})
_SKIP_REASONS = frozenset({"tool_unavailable", "no_case_configured"})

_RETRIEVE_FORBIDDEN = (
    "expected_answer_mode",
    "expected_citations",
    "tool_name",
    "arguments",
    "expected_tool_result",
)
_ASK_FORBIDDEN = ("tool_name", "arguments", "expected_tool_result")
_PACK_OFF_FORBIDDEN = (
    "expected_answer_mode",
    "expected_citations",
    "expected_source_ids",
    "tool_name",
    "arguments",
    "expected_tool_result",
)
_INVOKE_FORBIDDEN = (
    "query",
    "k",
    "expected_source_ids",
    "expected_citations",
    "expected_answer_mode",
)


def _require_text(value: object, field_name: str) -> str:
    """Reject anything that is not a non-blank string."""
    if not isinstance(value, str):
        raise ApplicationValidationError(
            f"{field_name} must be a non-empty string, got {type(value).__name__}"
        )
    if not value.strip():
        raise ApplicationValidationError(f"{field_name} must be non-empty")
    return value


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    """Reject non-sequence collections (and strings/bytes)."""
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ApplicationValidationError(
            f"{field_name} must be a sequence, got {type(value).__name__}"
        )
    return value


def _require_positive_int(value: object, field_name: str) -> int:
    """Reject missing or non-positive integers."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApplicationValidationError(
            f"{field_name} must be a positive integer, got {type(value).__name__}"
        )
    if value <= 0:
        raise ApplicationValidationError(
            f"{field_name} must be a positive integer, got {value}"
        )
    return value


def _require_non_negative_int(value: object, field_name: str) -> int:
    """Reject missing or negative integers."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApplicationValidationError(
            f"{field_name} must be a non-negative integer, "
            f"got {type(value).__name__}"
        )
    if value < 0:
        raise ApplicationValidationError(
            f"{field_name} must be a non-negative integer, got {value}"
        )
    return value


def _copy_json_value(value: object, field_name: str) -> object:
    """Deep-copy a JSON-compatible value."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Mapping):
        copied: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ApplicationValidationError(
                    f"{field_name} keys must be non-blank strings, "
                    f"got {type(key).__name__}"
                )
            copied[key] = _copy_json_value(item, f"{field_name}.{key}")
        return copied
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [
            _copy_json_value(item, f"{field_name}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ApplicationValidationError(
        f"{field_name} must be JSON-compatible, got {type(value).__name__}"
    )


def _copy_json_mapping(value: object, field_name: str) -> dict[str, object]:
    """Copy a JSON object mapping."""
    if not isinstance(value, Mapping):
        raise ApplicationValidationError(
            f"{field_name} must be a mapping, got {type(value).__name__}"
        )
    copied = _copy_json_value(value, field_name)
    if not isinstance(copied, dict):
        raise ApplicationValidationError(
            f"{field_name} must be a mapping, got {type(value).__name__}"
        )
    return copied


def _forbidden_if_set(case: object, names: Sequence[str], kind: str) -> None:
    """Reject fields that the case kind must not carry."""
    for name in names:
        if getattr(case, name) is not None:
            raise ApplicationValidationError(
                f"{name} is not allowed for kind {kind}"
            )


def _require_query_and_k(case: EvalCase) -> None:
    _require_text(case.query, "query")
    _require_positive_int(case.k, "k")


@dataclass(frozen=True, slots=True)
class EvalCitationLabel:
    """Gold citation identity without quote or document text.

    Args:
        source_id (str): Required non-blank source identifier.
        source_type (str): Required non-blank open source kind.
        chunk_index (int | None): Optional non-negative chunk index.
    """

    source_id: str
    source_type: str
    chunk_index: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.source_type, "source_type")
        if self.chunk_index is None:
            return
        if not isinstance(self.chunk_index, int) or isinstance(self.chunk_index, bool):
            raise ApplicationValidationError(
                "chunk_index must be a non-negative integer, "
                f"got {type(self.chunk_index).__name__}"
            )
        if self.chunk_index < 0:
            raise ApplicationValidationError(
                f"chunk_index must be a non-negative integer, got {self.chunk_index}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class EvalCase:
    """One eval suite case, discriminated by ``kind``.

    Args:
        id (str): Non-blank case identifier.
        case_class (str): Required coverage class.
        kind (str): ``retrieve``, ``ask``, ``invoke_tool``, or ``pack_off``.
        query (str | None): Query for retrieve, ask, and pack-off cases.
        k (int | None): Positive retrieval limit for retrieve, ask, and pack-off.
        expected_source_ids (Sequence[str] | None): Gold source ids for retrieval.
        expected_answer_mode (str | None): ``grounded`` or ``insufficient`` for ask.
        expected_citations (Sequence[EvalCitationLabel] | None): Gold citations.
        tool_name (str | None): Tool identifier for invoke_tool.
        arguments (Mapping[str, object] | None): JSON-compatible tool arguments.
        expected_tool_result (Mapping[str, object] | None): Expected JSON subset.
    """

    id: str
    case_class: str
    kind: str
    query: str | None = None
    k: int | None = None
    expected_source_ids: Sequence[str] | None = None
    expected_answer_mode: str | None = None
    expected_citations: Sequence[EvalCitationLabel] | None = None
    tool_name: str | None = None
    arguments: Mapping[str, object] | None = None
    expected_tool_result: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        _require_text(self.case_class, "case_class")
        if self.case_class not in REQUIRED_CASE_CLASSES:
            raise ApplicationValidationError(
                f"case_class must be a required eval class, got {self.case_class}"
            )
        _require_text(self.kind, "kind")
        if self.kind not in _KINDS:
            raise ApplicationValidationError(
                f"kind must be retrieve, ask, invoke_tool, or pack_off, got {self.kind}"
            )
        if self.kind == "pack_off" and self.case_class != "pack_off":
            raise ApplicationValidationError(
                "pack_off kind requires case_class pack_off"
            )
        if self.case_class == "pack_off" and self.kind != "pack_off":
            raise ApplicationValidationError(
                "pack_off class requires kind pack_off"
            )
        if self.kind == "invoke_tool" and self.case_class != "tool":
            raise ApplicationValidationError("invoke_tool kind requires case_class tool")
        if self.case_class == "tool" and self.kind != "invoke_tool":
            raise ApplicationValidationError("tool class requires kind invoke_tool")
        if self.kind == "retrieve":
            self._validate_retrieve()
        elif self.kind == "ask":
            self._validate_ask()
        elif self.kind == "pack_off":
            self._validate_pack_off()
        else:
            self._validate_invoke_tool()

    def _copy_source_ids(self) -> tuple[str, ...]:
        ids = _require_sequence(self.expected_source_ids, "expected_source_ids")
        if not ids:
            raise ApplicationValidationError(
                "expected_source_ids must contain at least one item"
            )
        copied: list[str] = []
        for index, item in enumerate(ids):
            copied.append(_require_text(item, f"expected_source_ids[{index}]"))
        object.__setattr__(self, "expected_source_ids", tuple(copied))
        return tuple(copied)

    def _copy_citations(self) -> tuple[EvalCitationLabel, ...]:
        labels = _require_sequence(self.expected_citations, "expected_citations")
        copied: list[EvalCitationLabel] = []
        for index, item in enumerate(labels):
            if not isinstance(item, EvalCitationLabel):
                raise ApplicationValidationError(
                    f"expected_citations[{index}] must be an EvalCitationLabel, "
                    f"got {type(item).__name__}"
                )
            copied.append(item)
        object.__setattr__(self, "expected_citations", tuple(copied))
        return tuple(copied)

    def _validate_retrieve(self) -> None:
        _forbidden_if_set(self, _RETRIEVE_FORBIDDEN, "retrieve")
        _require_query_and_k(self)
        if self.expected_source_ids is None:
            raise ApplicationValidationError(
                "expected_source_ids is required for kind retrieve"
            )
        self._copy_source_ids()

    def _validate_ask(self) -> None:
        _forbidden_if_set(self, _ASK_FORBIDDEN, "ask")
        _require_query_and_k(self)
        if self.expected_answer_mode not in _ANSWER_MODES:
            raise ApplicationValidationError(
                "expected_answer_mode must be grounded or insufficient"
            )
        if self.expected_citations is None:
            raise ApplicationValidationError(
                "expected_citations is required for kind ask"
            )
        labels = self._copy_citations()
        if self.expected_answer_mode == "insufficient" and labels:
            raise ApplicationValidationError(
                "expected_citations must be empty when expected_answer_mode is "
                "insufficient"
            )
        if self.case_class == "irrelevant":
            if self.expected_source_ids is not None:
                raise ApplicationValidationError(
                    "expected_source_ids is not allowed for class irrelevant"
                )
            if self.expected_answer_mode != "insufficient":
                raise ApplicationValidationError(
                    "irrelevant ask cases require expected_answer_mode insufficient"
                )
            return
        if self.expected_source_ids is None:
            raise ApplicationValidationError(
                "expected_source_ids is required for retrieval-bearing ask classes"
            )
        self._copy_source_ids()

    def _validate_pack_off(self) -> None:
        _forbidden_if_set(self, _PACK_OFF_FORBIDDEN, "pack_off")
        _require_query_and_k(self)

    def _validate_invoke_tool(self) -> None:
        _forbidden_if_set(self, _INVOKE_FORBIDDEN, "invoke_tool")
        _require_text(self.tool_name, "tool_name")
        if self.arguments is None:
            raise ApplicationValidationError(
                "arguments is required for kind invoke_tool"
            )
        object.__setattr__(self, "arguments", _copy_json_mapping(self.arguments, "arguments"))
        if self.expected_tool_result is None:
            raise ApplicationValidationError(
                "expected_tool_result is required for kind invoke_tool"
            )
        object.__setattr__(
            self,
            "expected_tool_result",
            _copy_json_mapping(self.expected_tool_result, "expected_tool_result"),
        )


@dataclass(frozen=True, slots=True)
class EvalCaseResult:
    """Outcome of one executed eval case.

    Args:
        case_id (str): Case identifier.
        case_class (str): Coverage class.
        kind (str): Case kind.
        status (str): ``pass``, ``fail``, or ``skip``.
        metrics (Mapping[str, int | float | bool]): Copied numeric/bool metrics.
        checks (Mapping[str, bool]): Copied named checks.
        failed_checks (Sequence[str]): Check names that were false.
        skip_reason (str | None): ``tool_unavailable`` when skipped, else ``None``.
        error_type (str | None): Exception type name on an execution failure.
    """

    case_id: str
    case_class: str
    kind: str
    status: str
    metrics: Mapping[str, int | float | bool]
    checks: Mapping[str, bool]
    failed_checks: Sequence[str]
    skip_reason: str | None = None
    error_type: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.case_id, "case_id")
        _require_text(self.case_class, "case_class")
        _require_text(self.kind, "kind")
        if self.status not in _RESULT_STATUSES:
            raise ApplicationValidationError(
                "status must be pass, fail, or skip"
            )
        if not isinstance(self.metrics, Mapping):
            raise ApplicationValidationError(
                f"metrics must be a mapping, got {type(self.metrics).__name__}"
            )
        metrics: dict[str, int | float | bool] = {}
        for key, value in self.metrics.items():
            _require_text(key, "metrics key")
            if isinstance(value, bool):
                metrics[key] = value
            elif isinstance(value, int):
                metrics[key] = value
            elif isinstance(value, float):
                metrics[key] = value
            else:
                raise ApplicationValidationError(
                    f"metrics[{key}] must be int, float, or bool, "
                    f"got {type(value).__name__}"
                )
        object.__setattr__(self, "metrics", metrics)
        if not isinstance(self.checks, Mapping):
            raise ApplicationValidationError(
                f"checks must be a mapping, got {type(self.checks).__name__}"
            )
        checks: dict[str, bool] = {}
        for key, value in self.checks.items():
            _require_text(key, "checks key")
            if not isinstance(value, bool):
                raise ApplicationValidationError(
                    f"checks[{key}] must be a bool, got {type(value).__name__}"
                )
            checks[key] = value
        object.__setattr__(self, "checks", checks)
        failed = _require_sequence(self.failed_checks, "failed_checks")
        copied_failed: list[str] = []
        for index, item in enumerate(failed):
            copied_failed.append(_require_text(item, f"failed_checks[{index}]"))
        object.__setattr__(self, "failed_checks", tuple(copied_failed))
        if self.skip_reason is not None:
            _require_text(self.skip_reason, "skip_reason")
            if self.skip_reason not in _SKIP_REASONS:
                raise ApplicationValidationError(
                    "skip_reason must be tool_unavailable or no_case_configured"
                )
            if self.status != "skip":
                raise ApplicationValidationError(
                    "skip_reason is only allowed when status is skip"
                )
        elif self.status == "skip":
            raise ApplicationValidationError(
                "skip_reason is required when status is skip"
            )
        if self.error_type is not None:
            _require_text(self.error_type, "error_type")
            if self.status != "fail":
                raise ApplicationValidationError(
                    "error_type is only allowed when status is fail"
                )


@dataclass(frozen=True, slots=True)
class EvalAggregate:
    """Mean metric over executed retrieval-bearing cases.

    Args:
        value (float): Mean, or ``0.0`` when the denominator is ``0``.
        denominator (int): Number of executed retrieval-bearing cases.
    """

    value: float
    denominator: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ApplicationValidationError(
                f"value must be a number, got {type(self.value).__name__}"
            )
        object.__setattr__(self, "value", float(self.value))
        _require_non_negative_int(self.denominator, "denominator")


@dataclass(frozen=True, slots=True)
class EvalCoverageEntry:
    """Whether a required case class ran.

    Args:
        state (str): ``exercised`` or ``skipped``.
        reason (str | None): Skip reason, or ``None`` when exercised.
    """

    state: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.state not in _COVERAGE_STATES:
            raise ApplicationValidationError(
                "state must be exercised or skipped"
            )
        if self.state == "skipped":
            if self.reason not in _SKIP_REASONS:
                raise ApplicationValidationError(
                    "skipped coverage requires no_case_configured or tool_unavailable"
                )
        elif self.reason is not None:
            raise ApplicationValidationError(
                "exercised coverage must not set a skip reason"
            )


@dataclass(frozen=True, slots=True)
class EvalReport:
    """Offline eval suite report.

    Args:
        schema_version (str): Literal ``kernector.eval.v1``.
        mode (str): Always ``offline``.
        results (Sequence[EvalCaseResult]): Per-case outcomes in suite order.
        pass_count (int): Cases with status ``pass``.
        fail_count (int): Cases with status ``fail``.
        skip_count (int): Cases with status ``skip``.
        aggregates (Mapping[str, EvalAggregate]): Hit@k, MRR, source_recall_at_k.
        coverage (Mapping[str, EvalCoverageEntry]): Every required class.
    """

    schema_version: str
    mode: str
    results: Sequence[EvalCaseResult]
    pass_count: int
    fail_count: int
    skip_count: int
    aggregates: Mapping[str, EvalAggregate]
    coverage: Mapping[str, EvalCoverageEntry]

    def __post_init__(self) -> None:
        if self.schema_version != EVAL_SCHEMA_VERSION:
            raise ApplicationValidationError(
                "schema_version must be kernector.eval.v1"
            )
        if self.mode != EVAL_MODE_OFFLINE:
            raise ApplicationValidationError("mode must be offline")
        results = _require_sequence(self.results, "results")
        copied_results: list[EvalCaseResult] = []
        for index, item in enumerate(results):
            if not isinstance(item, EvalCaseResult):
                raise ApplicationValidationError(
                    f"results[{index}] must be an EvalCaseResult, "
                    f"got {type(item).__name__}"
                )
            copied_results.append(item)
        object.__setattr__(self, "results", tuple(copied_results))
        _require_non_negative_int(self.pass_count, "pass_count")
        _require_non_negative_int(self.fail_count, "fail_count")
        _require_non_negative_int(self.skip_count, "skip_count")
        for name, status in (
            ("pass_count", "pass"),
            ("fail_count", "fail"),
            ("skip_count", "skip"),
        ):
            actual = sum(1 for item in copied_results if item.status == status)
            if getattr(self, name) != actual:
                raise ApplicationValidationError(
                    f"{name} must equal {actual} results with status {status}, "
                    f"got {getattr(self, name)}"
                )
        if not isinstance(self.aggregates, Mapping):
            raise ApplicationValidationError(
                f"aggregates must be a mapping, got {type(self.aggregates).__name__}"
            )
        aggregates: dict[str, EvalAggregate] = {}
        for key, value in self.aggregates.items():
            _require_text(key, "aggregates key")
            if not isinstance(value, EvalAggregate):
                raise ApplicationValidationError(
                    f"aggregates[{key}] must be an EvalAggregate, "
                    f"got {type(value).__name__}"
                )
            aggregates[key] = value
        for required in REQUIRED_AGGREGATES:
            if required not in aggregates:
                raise ApplicationValidationError(
                    f"aggregates missing required metric {required}"
                )
        object.__setattr__(self, "aggregates", aggregates)
        if not isinstance(self.coverage, Mapping):
            raise ApplicationValidationError(
                f"coverage must be a mapping, got {type(self.coverage).__name__}"
            )
        coverage: dict[str, EvalCoverageEntry] = {}
        for key, value in self.coverage.items():
            _require_text(key, "coverage key")
            if not isinstance(value, EvalCoverageEntry):
                raise ApplicationValidationError(
                    f"coverage[{key}] must be an EvalCoverageEntry, "
                    f"got {type(value).__name__}"
                )
            coverage[key] = value
        for required in REQUIRED_CASE_CLASSES:
            if required not in coverage:
                raise ApplicationValidationError(
                    f"coverage missing required class {required}"
                )
        object.__setattr__(self, "coverage", coverage)


def eval_report_to_dict(report: EvalReport) -> dict[str, object]:
    """Convert ``report`` to a JSON-compatible mapping.

    Args:
        report (EvalReport): Validated eval report.

    Returns:
        dict[str, object]: Nested JSON-compatible structure.
    """
    return {
        "schema_version": report.schema_version,
        "mode": report.mode,
        "pass_count": report.pass_count,
        "fail_count": report.fail_count,
        "skip_count": report.skip_count,
        "aggregates": {
            name: {"value": item.value, "denominator": item.denominator}
            for name, item in report.aggregates.items()
        },
        "coverage": {
            name: {"state": item.state, "reason": item.reason}
            for name, item in report.coverage.items()
        },
        "results": [
            {
                "case_id": item.case_id,
                "case_class": item.case_class,
                "kind": item.kind,
                "status": item.status,
                "metrics": dict(item.metrics),
                "checks": dict(item.checks),
                "failed_checks": list(item.failed_checks),
                "skip_reason": item.skip_reason,
                "error_type": item.error_type,
            }
            for item in report.results
        ],
    }


def eval_report_to_json(report: EvalReport) -> str:
    """Serialize ``report`` to deterministic JSON.

    Args:
        report (EvalReport): Validated eval report.

    Returns:
        str: JSON text with sorted keys and a trailing newline.
    """
    return json.dumps(eval_report_to_dict(report), indent=2, sort_keys=True) + "\n"


def eval_report_to_markdown(report: EvalReport) -> str:
    """Serialize ``report`` to a fixed-section Markdown document.

    Args:
        report (EvalReport): Validated eval report.

    Returns:
        str: Markdown text with a trailing newline.
    """
    lines = [
        "# Kernector eval report",
        "",
        f"schema_version: {report.schema_version}",
        f"mode: {report.mode}",
        "",
        "## Counts",
        "",
        f"- pass: {report.pass_count}",
        f"- fail: {report.fail_count}",
        f"- skip: {report.skip_count}",
        "",
        "## Aggregates",
        "",
    ]
    for name in REQUIRED_AGGREGATES:
        item = report.aggregates[name]
        lines.append(f"- {name}: {item.value:.4f} (n={item.denominator})")
    lines.extend(["", "## Coverage", ""])
    for name in REQUIRED_CASE_CLASSES:
        entry = report.coverage[name]
        if entry.state == "skipped":
            lines.append(f"- {name}: skipped ({entry.reason})")
        else:
            lines.append(f"- {name}: exercised")
    lines.extend(["", "## Results", ""])
    if not report.results:
        lines.append("No cases.")
    for item in report.results:
        lines.extend(
            [
                f"### {item.case_id}",
                "",
                f"- class: {item.case_class}",
                f"- kind: {item.kind}",
                f"- status: {item.status}",
                f"- metrics: {json.dumps(dict(item.metrics), sort_keys=True)}",
                f"- checks: {json.dumps(dict(item.checks), sort_keys=True)}",
                f"- failed_checks: {', '.join(item.failed_checks) or 'none'}",
                f"- skip_reason: {item.skip_reason or 'none'}",
                f"- error_type: {item.error_type or 'none'}",
                "",
            ]
        )
    text = "\n".join(lines).rstrip() + "\n"
    return text
