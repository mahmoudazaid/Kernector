"""Offline RAG and tool evaluation use case."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json

from application.contracts import (
    AskRequest,
    AskResponse,
    Citation,
    InvokeToolRequest,
    InvokeToolResponse,
    RetrieveRequest,
    RetrieveResponse,
)
from application.evaluation_contracts import (
    EVAL_MODE_OFFLINE,
    EVAL_SCHEMA_VERSION,
    REQUIRED_CASE_CLASSES,
    EvalAggregate,
    EvalCase,
    EvalCaseResult,
    EvalCitationLabel,
    EvalCoverageEntry,
    EvalReport,
)
from application.grounded_rag_policy import INSUFFICIENT_KNOWLEDGE_ANSWER
from domain.knowledge import ScoredChunk


class EvaluateKnowledge:
    """Score a curated eval suite against retrieve, ask, pack-off, and invoke seams.

    Application tests inject fakes. Composition injects BM25-only retrieve, an
    identity-rewritten ask, a pack-disabled ToolAugmentedAsk, and optional
    InvokeTool.

    Args:
        retrieve: Seam returning ``RetrieveResponse`` for a ``RetrieveRequest``.
        ask: Grounded ask seam (packs irrelevant).
        ask_pack_off: Ask seam that must fall through with ``path=rag``.
        invoke: Optional tool invoke seam; ``None`` skips invoke_tool cases.
    """

    def __init__(
        self,
        retrieve: object,
        ask: object,
        ask_pack_off: object,
        invoke: object | None = None,
    ) -> None:
        self._retrieve = retrieve
        self._ask = ask
        self._ask_pack_off = ask_pack_off
        self._invoke = invoke

    def execute(self, cases: Sequence[EvalCase]) -> EvalReport:
        """Run every case, catch per-case failures, and return an offline report.

        Args:
            cases (Sequence[EvalCase]): Suite in caller order.

        Returns:
            EvalReport: Results in input order, aggregates, and coverage.
        """
        results: list[EvalCaseResult] = []
        for case in cases:
            try:
                results.append(self._run_case(case))
            except Exception:
                results.append(
                    EvalCaseResult(
                        case_id=case.id,
                        case_class=case.case_class,
                        kind=case.kind,
                        status="fail",
                        metrics={},
                        checks={"execution_error": False},
                        failed_checks=("execution_error",),
                    )
                )
        return _build_report(tuple(results))

    def _run_case(self, case: EvalCase) -> EvalCaseResult:
        if case.kind == "retrieve":
            return self._run_retrieve(case)
        if case.kind == "ask":
            return self._run_ask(case)
        if case.kind == "pack_off":
            return self._run_pack_off(case)
        return self._run_invoke(case)

    def _run_retrieve(self, case: EvalCase) -> EvalCaseResult:
        response = self._retrieve.execute(
            RetrieveRequest(query=case.query, retrieval_limit=case.k)
        )
        metrics, checks = _retrieval_scores(response.hits, case)
        if case.case_class == "cross_source":
            checks["source_recall_at_k"] = metrics["source_recall_at_k"] == 1.0
        else:
            checks["hit_at_k"] = metrics["hit_at_k"] == 1.0
        return _result_from_checks(case, metrics, checks)

    def _run_ask(self, case: EvalCase) -> EvalCaseResult:
        retrieve_response: RetrieveResponse = self._retrieve.execute(
            RetrieveRequest(query=case.query, retrieval_limit=case.k)
        )
        ask_response: AskResponse = self._ask.execute(
            AskRequest(query=case.query, retrieval_limit=case.k)
        )
        metrics: dict[str, int | float | bool] = {}
        checks: dict[str, bool] = {}
        if case.expected_source_ids:
            retrieval_metrics, _ = _retrieval_scores(
                retrieve_response.hits, case
            )
            metrics.update(retrieval_metrics)
        if case.expected_answer_mode == "insufficient":
            checks["answer_insufficient"] = (
                ask_response.answer == INSUFFICIENT_KNOWLEDGE_ANSWER
            )
            checks["empty_citations"] = tuple(ask_response.citations) == ()
            checks["outcome_insufficient"] = (
                ask_response.run is not None
                and ask_response.run.outcome == "insufficient"
            )
            return _result_from_checks(case, metrics, checks)

        checks["answer_grounded"] = (
            ask_response.answer != INSUFFICIENT_KNOWLEDGE_ANSWER
        )
        checks.update(
            _citation_checks(
                ask_response.citations,
                retrieve_response.hits,
                case.expected_citations or (),
            )
        )
        if case.case_class == "conflicting":
            expected = tuple(case.expected_source_ids or ())
            checks["conflicting_sources_retrieved"] = _sources_in_hits(
                expected, retrieve_response.hits
            )
            checks["conflicting_sources_cited"] = _sources_in_citations(
                expected, ask_response.citations
            )
        if case.case_class == "unknown_source_kind":
            labels = tuple(case.expected_citations or ())
            checks["unknown_source_type_retrieved"] = _labels_in_hits(
                labels, retrieve_response.hits
            )
            checks["unknown_source_type_cited"] = _labels_in_citations(
                labels, ask_response.citations
            )
        return _result_from_checks(case, metrics, checks)

    def _run_pack_off(self, case: EvalCase) -> EvalCaseResult:
        response: AskResponse = self._ask_pack_off.execute(
            AskRequest(query=case.query, retrieval_limit=case.k)
        )
        run = response.run
        checks = {
            "empty_tool_outputs": tuple(response.tool_outputs) == (),
            "path_rag": run is not None and run.path == "rag",
            "pack_none": run is not None and run.pack is None,
        }
        return _result_from_checks(case, {}, checks)

    def _run_invoke(self, case: EvalCase) -> EvalCaseResult:
        if self._invoke is None:
            return EvalCaseResult(
                case_id=case.id,
                case_class=case.case_class,
                kind=case.kind,
                status="skip",
                metrics={},
                checks={},
                failed_checks=(),
                skip_reason="tool_unavailable",
            )
        response: InvokeToolResponse = self._invoke.execute(
            InvokeToolRequest(tool_name=case.tool_name, arguments=case.arguments or {})
        )
        checks: dict[str, bool] = {"tool_name": response.tool_name == case.tool_name}
        parsed = _parse_tool_object(response.result)
        checks["tool_result_json"] = parsed is not None
        if parsed is None:
            checks["expected_tool_result"] = False
        else:
            checks["expected_tool_result"] = _is_json_subset(
                case.expected_tool_result or {}, parsed
            )
        return _result_from_checks(case, {}, checks)


def _retrieval_scores(
    hits: Sequence[ScoredChunk], case: EvalCase
) -> tuple[dict[str, int | float | bool], dict[str, bool]]:
    expected = tuple(case.expected_source_ids or ())
    top = tuple(hits[: case.k])
    source_ids = tuple(hit.chunk.reference.source_id for hit in top)
    hit_at_k = 1.0 if any(item in source_ids for item in expected) else 0.0
    mrr = 0.0
    for rank, source_id in enumerate(source_ids, start=1):
        if source_id in expected:
            mrr = 1.0 / rank
            break
    expected_set = set(expected)
    found = {item for item in source_ids if item in expected_set}
    recall = (len(found) / len(expected_set)) if expected_set else 0.0
    metrics: dict[str, int | float | bool] = {
        "hit_at_k": hit_at_k,
        "mrr": mrr,
        "source_recall_at_k": recall,
    }
    return metrics, {}


def _citation_identity(citation: Citation) -> tuple[object, ...]:
    reference = citation.reference
    if citation.chunk_index is None:
        return (reference.source_id, reference.source_type)
    return (reference.source_id, reference.source_type, citation.chunk_index)


def _hit_identities(hits: Sequence[ScoredChunk]) -> set[tuple[object, ...]]:
    identities: set[tuple[object, ...]] = set()
    for hit in hits:
        reference = hit.chunk.reference
        identities.add((reference.source_id, reference.source_type, hit.chunk.index))
        identities.add((reference.source_id, reference.source_type))
    return identities


def _label_matches_citation(
    label: EvalCitationLabel, citation: Citation
) -> bool:
    if citation.reference.source_id != label.source_id:
        return False
    if citation.reference.source_type != label.source_type:
        return False
    if label.chunk_index is None:
        return True
    return citation.chunk_index == label.chunk_index


def _citation_checks(
    citations: Sequence[Citation],
    hits: Sequence[ScoredChunk],
    gold: Sequence[EvalCitationLabel],
) -> dict[str, bool]:
    hit_ids = _hit_identities(hits)
    hit_precision = all(_citation_identity(item) in hit_ids for item in citations)
    gold_recall = all(
        any(_label_matches_citation(label, citation) for citation in citations)
        for label in gold
    )
    gold_precision = all(
        any(_label_matches_citation(label, citation) for label in gold)
        for citation in citations
    )
    return {
        "citation_hit_precision": hit_precision,
        "citation_gold_recall": gold_recall,
        "citation_gold_precision": gold_precision,
    }


def _sources_in_hits(source_ids: Sequence[str], hits: Sequence[ScoredChunk]) -> bool:
    found = {hit.chunk.reference.source_id for hit in hits}
    return all(item in found for item in source_ids)


def _sources_in_citations(
    source_ids: Sequence[str], citations: Sequence[Citation]
) -> bool:
    found = {item.reference.source_id for item in citations}
    return all(item in found for item in source_ids)


def _labels_in_hits(
    labels: Sequence[EvalCitationLabel], hits: Sequence[ScoredChunk]
) -> bool:
    found = {(hit.chunk.reference.source_id, hit.chunk.reference.source_type) for hit in hits}
    return all((label.source_id, label.source_type) in found for label in labels)


def _labels_in_citations(
    labels: Sequence[EvalCitationLabel], citations: Sequence[Citation]
) -> bool:
    return all(
        any(_label_matches_citation(label, citation) for citation in citations)
        for label in labels
    )


def _parse_tool_object(raw: str) -> dict[str, object] | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _is_json_subset(expected: object, actual: object) -> bool:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return False
        return all(
            key in actual and _is_json_subset(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, Sequence) or isinstance(actual, (str, bytes)):
            return False
        if len(expected) != len(actual):
            return False
        return all(
            _is_json_subset(left, right)
            for left, right in zip(expected, actual, strict=True)
        )
    return expected == actual


def _result_from_checks(
    case: EvalCase,
    metrics: Mapping[str, int | float | bool],
    checks: Mapping[str, bool],
) -> EvalCaseResult:
    failed = tuple(name for name, passed in checks.items() if not passed)
    return EvalCaseResult(
        case_id=case.id,
        case_class=case.case_class,
        kind=case.kind,
        status="pass" if not failed else "fail",
        metrics=metrics,
        checks=checks,
        failed_checks=failed,
    )


def _is_retrieval_bearing(result: EvalCaseResult) -> bool:
    if result.status == "skip":
        return False
    if result.kind not in {"retrieve", "ask"}:
        return False
    return "hit_at_k" in result.metrics


def _build_report(results: tuple[EvalCaseResult, ...]) -> EvalReport:
    pass_count = sum(1 for item in results if item.status == "pass")
    fail_count = sum(1 for item in results if item.status == "fail")
    skip_count = sum(1 for item in results if item.status == "skip")
    retrieval = [item for item in results if _is_retrieval_bearing(item)]
    denom = len(retrieval)
    if denom == 0:
        aggregates = {
            "hit_at_k": EvalAggregate(0.0, 0),
            "mrr": EvalAggregate(0.0, 0),
            "source_recall_at_k": EvalAggregate(0.0, 0),
        }
    else:
        aggregates = {
            name: EvalAggregate(
                sum(float(item.metrics[name]) for item in retrieval) / denom,
                denom,
            )
            for name in ("hit_at_k", "mrr", "source_recall_at_k")
        }
    exercised: set[str] = set()
    skipped_tool = False
    for item in results:
        if item.status == "skip":
            if item.case_class == "tool" and item.skip_reason == "tool_unavailable":
                skipped_tool = True
            continue
        exercised.add(item.case_class)
    coverage: dict[str, EvalCoverageEntry] = {}
    for name in REQUIRED_CASE_CLASSES:
        if name in exercised:
            coverage[name] = EvalCoverageEntry("exercised")
        elif name == "tool" and skipped_tool and "tool" not in exercised:
            coverage[name] = EvalCoverageEntry("skipped", "tool_unavailable")
        else:
            coverage[name] = EvalCoverageEntry("skipped", "no_case_configured")
    return EvalReport(
        schema_version=EVAL_SCHEMA_VERSION,
        mode=EVAL_MODE_OFFLINE,
        results=results,
        pass_count=pass_count,
        fail_count=fail_count,
        skip_count=skip_count,
        aggregates=aggregates,
        coverage=coverage,
    )
