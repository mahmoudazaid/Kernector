"""ChatModel-backed Software Delivery requirements analysis."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence

from domain.errors import ToolFailureError
from domain.knowledge import ScoredChunk, SourceReference
from domain.models import AskResult
from domain.ports import ChatModel
from packs.software_delivery.errors import MissingEvidenceError
from packs.software_delivery.evidence_bundle import evidence_bundle_from_hits
from packs.software_delivery.limits import (
    MAX_EVIDENCE_IDS_PER_FINDING,
    MAX_FINDINGS_PER_SECTION,
    MAX_MODEL_RESPONSE_CHARS,
    REQUIREMENTS_ANALYSIS_MODEL_SETTINGS,
)
from packs.software_delivery.requirements_analysis_contracts import (
    AnalyzeRequirementsRequest,
    RequirementsAnalysisResult,
    RequirementsFinding,
)
from packs.software_delivery.requirements_analysis_prompt import (
    build_requirements_analysis_prompt,
)

RetrieveEvidence = Callable[[str], Sequence[ScoredChunk]]

_FINDING_KEYS = frozenset({"statement", "evidence_ids"})
_ROOT_KEYS = frozenset(
    {
        "summary",
        "acceptance_criteria_gaps",
        "risks",
        "clarification_questions",
    }
)
_SECTION_FIELDS = (
    "acceptance_criteria_gaps",
    "risks",
    "clarification_questions",
)


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
            ProviderError: Propagated unchanged from ``ChatModel.complete()``.
            ToolFailureError: Invalid or unusable model output.
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
        result = self._chat_model.complete(
            system, messages, dict(REQUIREMENTS_ANALYSIS_MODEL_SETTINGS)
        )

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

        parsed = _parse_payload(payload, evidence_by_id)
        evidence = _resolve_evidence(hits, parsed)
        try:
            return RequirementsAnalysisResult(
                parsed.summary,
                parsed.acceptance_criteria_gaps,
                parsed.risks,
                parsed.clarification_questions,
                evidence,
            )
        except ValueError as exc:
            raise ToolFailureError(str(exc)) from exc


def _resolve_evidence(
    hits: Sequence[ScoredChunk],
    parsed: RequirementsAnalysisResult,
) -> tuple[ScoredChunk, ...]:
    """Return cited chunks for findings, or all retrieved hits when sections are empty."""
    all_refs = tuple(
        ref
        for section in (
            parsed.acceptance_criteria_gaps,
            parsed.risks,
            parsed.clarification_questions,
        )
        for finding in section
        for ref in finding.references
    )
    if all_refs:
        return cited_chunks(hits, references=all_refs)
    return tuple(hits)


def _parse_payload(
    payload: object,
    evidence_by_id: Mapping[str, SourceReference],
) -> RequirementsAnalysisResult:
    if not isinstance(payload, dict):
        raise ToolFailureError("model JSON must be an object")
    unknown_root = set(payload) - _ROOT_KEYS
    if unknown_root:
        raise ToolFailureError(
            f"unexpected model fields: {sorted(unknown_root)}"
        )
    for required in _ROOT_KEYS:
        if required not in payload:
            raise ToolFailureError(f"{required} is required")

    summary = payload["summary"]
    if not isinstance(summary, str) or not summary.strip():
        raise ToolFailureError("summary must be a non-blank string")

    sections = {
        field: _parse_section(field, payload[field], evidence_by_id)
        for field in _SECTION_FIELDS
    }
    return RequirementsAnalysisResult(
        summary,
        sections["acceptance_criteria_gaps"],
        sections["risks"],
        sections["clarification_questions"],
        (),
    )


def _parse_section(
    field_name: str,
    raw_section: object,
    evidence_by_id: Mapping[str, SourceReference],
) -> tuple[RequirementsFinding, ...]:
    if isinstance(raw_section, (str, bytes)) or not isinstance(raw_section, Sequence):
        raise ToolFailureError(f"{field_name} must be a sequence")
    if len(raw_section) > MAX_FINDINGS_PER_SECTION:
        raise ToolFailureError(
            f"{field_name} must have at most {MAX_FINDINGS_PER_SECTION} items"
        )
    if len(raw_section) == 0:
        return ()

    parsed: list[RequirementsFinding] = []
    for item in raw_section:
        parsed.append(_parse_finding(item, field_name, evidence_by_id))
    return tuple(parsed)


def _parse_finding(
    item: object,
    field_name: str,
    evidence_by_id: Mapping[str, SourceReference],
) -> RequirementsFinding:
    if not isinstance(item, Mapping):
        raise ToolFailureError(f"{field_name} item must be an object")
    for key in item:
        if not isinstance(key, str):
            raise ToolFailureError(f"{field_name} item keys must be strings")
    unknown = set(item) - _FINDING_KEYS
    if unknown:
        raise ToolFailureError(
            f"unexpected {field_name} item fields: {sorted(unknown)}"
        )
    for required in _FINDING_KEYS:
        if required not in item:
            raise ToolFailureError(f"{required} is required")

    statement = item["statement"]
    if not isinstance(statement, str) or not statement.strip():
        raise ToolFailureError("statement must be a non-blank string")

    references = _resolve_evidence_ids(item["evidence_ids"], evidence_by_id)
    try:
        return RequirementsFinding(statement, references)
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
