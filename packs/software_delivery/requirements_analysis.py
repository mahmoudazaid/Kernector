"""ChatModel-backed Software Delivery requirements analysis."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence

from domain.errors import ProviderError, ToolFailureError
from domain.knowledge import ScoredChunk, SourceReference
from domain.models import AskResult
from domain.ports import ChatModel
from packs.software_delivery.errors import MissingEvidenceError
from packs.software_delivery.evidence_bundle import evidence_bundle_from_hits
from packs.software_delivery.limits import (
    MAX_EVIDENCE_IDS_PER_FINDING,
    MAX_MODEL_RESPONSE_CHARS,
    REQUIREMENTS_ANALYSIS_MODEL_SETTINGS,
)
from packs.software_delivery.requirements_analysis_contracts import (
    ANALYSIS_CATEGORIES,
    AnalyzeRequirementsRequest,
    RequirementsAnalysisResult,
    RequirementsFinding,
)
from packs.software_delivery.requirements_analysis_prompt import (
    build_requirements_analysis_prompt,
)

RetrieveEvidence = Callable[[str], Sequence[ScoredChunk]]

_FINDING_KEYS = frozenset({"category", "statement", "evidence_ids"})
_ROOT_KEYS = frozenset({"answer", "findings"})


def cited_chunks(
    hits: Sequence[ScoredChunk],
    *,
    references: Sequence[SourceReference],
) -> tuple[ScoredChunk, ...]:
    """Return hits whose provenance appears in references, in retrieval-rank order.

    Filters raw retrieval hits rather than a merged evidence bundle so
    ``chunk.index`` and per-chunk content stay available for citation assembly.
    """
    cited = {(ref.source_type, ref.source_id) for ref in references}
    return tuple(
        hit
        for hit in hits
        if (hit.chunk.reference.source_type, hit.chunk.reference.source_id) in cited
    )


class AnalyzeRequirements:
    """Analyze pasted requirements against multi-source retrieved evidence.

    Retrieval is injected; composition binds rewrite-and-retrieve with a
    relevance threshold and no source-type metadata filters. Override attempts
    embedded in the requirements text may propagate as
    ``ApplicationValidationError`` from ``RewriteAndRetrieveKnowledge`` before
    this use case runs.
    """

    def __init__(
        self,
        retrieve: RetrieveEvidence,
        chat_model: ChatModel,
    ) -> None:
        self._retrieve = retrieve
        self._chat_model = chat_model

    def execute(
        self, request: AnalyzeRequirementsRequest
    ) -> RequirementsAnalysisResult:
        """Retrieve evidence, prompt the model, and return cited findings.

        Raises:
            RequirementsAnalysisValidationError: Propagated from request or prompt
                validation before retrieval or the model.
            MissingEvidenceError: No hits returned from retrieval.
            ToolFailureError: Provider failure or invalid model output.
        """
        hits = tuple(self._retrieve(request.requirements))
        if not hits:
            raise MissingEvidenceError(
                "No relevant evidence was retrieved for the requirements"
            )

        bundle = evidence_bundle_from_hits(hits)
        system, messages, evidence_by_id = build_requirements_analysis_prompt(
            request, bundle
        )
        try:
            result = self._chat_model.complete(
                system, messages, dict(REQUIREMENTS_ANALYSIS_MODEL_SETTINGS)
            )
        except ProviderError as exc:
            raise ToolFailureError(
                "Requirements analysis model call failed"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - operational failure after valid args
            raise ToolFailureError("Requirements analysis failed") from exc

        if not isinstance(result, AskResult) or not isinstance(result.content, str):
            raise ToolFailureError(
                "Requirements analysis returned unusable model content"
            )
        if len(result.content) > MAX_MODEL_RESPONSE_CHARS:
            raise ToolFailureError(
                f"model response must be at most {MAX_MODEL_RESPONSE_CHARS} characters, "
                f"got {len(result.content)}"
            )

        try:
            payload = json.loads(result.content)
        except json.JSONDecodeError as exc:
            raise ToolFailureError("model response is not valid JSON") from exc

        answer, findings = _parse_payload(payload, evidence_by_id)
        all_refs = tuple(
            ref for finding in findings for ref in finding.references
        )
        evidence = cited_chunks(hits, references=all_refs)
        try:
            return RequirementsAnalysisResult(answer, findings, evidence)
        except ValueError as exc:
            raise ToolFailureError(str(exc)) from exc


def _parse_payload(
    payload: object,
    evidence_by_id: Mapping[str, SourceReference],
) -> tuple[str, tuple[RequirementsFinding, ...]]:
    if not isinstance(payload, dict):
        raise ToolFailureError("model JSON must be an object")
    unknown_root = set(payload) - _ROOT_KEYS
    if unknown_root:
        raise ToolFailureError(
            f"unexpected model fields: {sorted(unknown_root)}"
        )
    if "answer" not in payload:
        raise ToolFailureError("answer is required")
    if "findings" not in payload:
        raise ToolFailureError("findings is required")

    answer = payload["answer"]
    if not isinstance(answer, str) or not answer.strip():
        raise ToolFailureError("answer must be a non-blank string")

    raw_findings = payload["findings"]
    if isinstance(raw_findings, (str, bytes)) or not isinstance(
        raw_findings, Sequence
    ):
        raise ToolFailureError("findings must be a sequence")
    if len(raw_findings) == 0:
        raise ToolFailureError("findings must be non-empty")

    parsed: list[RequirementsFinding] = []
    for item in raw_findings:
        parsed.append(_parse_finding(item, evidence_by_id))
    return answer, tuple(parsed)


def _parse_finding(
    item: object,
    evidence_by_id: Mapping[str, SourceReference],
) -> RequirementsFinding:
    if not isinstance(item, Mapping):
        raise ToolFailureError("finding must be an object")
    for key in item:
        if not isinstance(key, str):
            raise ToolFailureError("finding keys must be strings")
    unknown = set(item) - _FINDING_KEYS
    if unknown:
        raise ToolFailureError(f"unexpected finding fields: {sorted(unknown)}")
    for required in _FINDING_KEYS:
        if required not in item:
            raise ToolFailureError(f"{required} is required")

    category = item["category"]
    if not isinstance(category, str) or category not in ANALYSIS_CATEGORIES:
        raise ToolFailureError(
            f"category must be one of {sorted(ANALYSIS_CATEGORIES)}"
        )

    statement = item["statement"]
    if not isinstance(statement, str) or not statement.strip():
        raise ToolFailureError("statement must be a non-blank string")

    references = _resolve_evidence_ids(item["evidence_ids"], evidence_by_id)
    try:
        return RequirementsFinding(category, statement, references)
    except ValueError as exc:
        raise ToolFailureError(str(exc)) from exc


def _resolve_evidence_ids(
    raw_ids: object,
    evidence_by_id: Mapping[str, SourceReference],
) -> tuple[SourceReference, ...]:
    if isinstance(raw_ids, (str, bytes)) or not isinstance(raw_ids, Sequence):
        raise ToolFailureError("evidence_ids must be a sequence")
    if len(raw_ids) == 0:
        raise ToolFailureError("evidence_ids must be non-empty")
    if len(raw_ids) > MAX_EVIDENCE_IDS_PER_FINDING:
        raise ToolFailureError(
            f"evidence_ids must have at most {MAX_EVIDENCE_IDS_PER_FINDING} items"
        )
    refs: list[SourceReference] = []
    for evidence_id in raw_ids:
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ToolFailureError("evidence_ids items must be non-blank strings")
        if evidence_id not in evidence_by_id:
            raise ToolFailureError(f"unknown evidence_id: {evidence_id!r}")
        refs.append(evidence_by_id[evidence_id])
    return tuple(refs)
