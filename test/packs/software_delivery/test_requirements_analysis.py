"""Tests for ChatModel-backed requirements analysis."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest

from domain.errors import DomainValidationError, ProviderError, ToolArgumentValidationError
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
)
from domain.models import AskResult, Message
from packs.software_delivery.errors import (
    MissingEvidenceError,
    RequirementsAnalysisOutputError,
    RequirementsAnalysisValidationError,
)
from packs.software_delivery.limits import (
    MAX_MODEL_RESPONSE_CHARS,
    MAX_REQUIREMENTS_CHARS,
    REQUIREMENTS_ANALYSIS_MODEL_SETTINGS,
)
from packs.software_delivery.requirements_analysis import AnalyzeRequirements
from packs.software_delivery.requirements_analysis_contracts import (
    AnalyzeRequirementsRequest,
)


class _RecordingRetrieve:
    def __init__(self, hits: Sequence[ScoredChunk]) -> None:
        self.hits = hits
        self.queries: list[str] = []

    def __call__(self, query: str) -> Sequence[ScoredChunk]:
        self.queries.append(query)
        return self.hits


class _FakeChat:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, Sequence[Message], Mapping[str, object]]] = []

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        self.calls.append((system, messages, settings))
        return AskResult(content=self.content)


def _hit(
    *,
    source_id: str = "US-1",
    source_type: str = "user_story",
    content: str = "Need MFA",
    index: int = 0,
) -> ScoredChunk:
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(
                SourceReference(source_id, source_type),
                extra={},
            ),
            index=index,
            content=content,
        ),
        score=0.9,
    )


def _request(requirements: str = "As a user I want MFA.") -> AnalyzeRequirementsRequest:
    return AnalyzeRequirementsRequest(requirements)


def _analysis_payload(
    *,
    evidence_ids: list[str] | None = None,
    gaps: list[dict[str, object]] | None = None,
    risks: list[dict[str, object]] | None = None,
    clarifications: list[dict[str, object]] | None = None,
) -> str:
    gap_item = {
        "statement": "No acceptance criterion covers lockout after failed MFA.",
        "evidence_ids": evidence_ids or ["e0"],
    }
    return json.dumps(
        {
            "summary": "MFA is required but lockout rules are unclear.",
            "acceptance_criteria_gaps": gaps if gaps is not None else [gap_item],
            "risks": risks if risks is not None else [],
            "clarification_questions": clarifications if clarifications is not None else [],
        }
    )


def test_analysis_returns_cited_findings_from_retrieved_evidence() -> None:
    requirements = "As a user I want MFA."
    retrieve = _RecordingRetrieve([_hit()])
    chat = _FakeChat(_analysis_payload())
    use_case = AnalyzeRequirements(retrieve, chat)

    result = use_case.execute(_request(requirements))

    assert retrieve.queries == [requirements]
    assert chat.calls[0][2] == dict(REQUIREMENTS_ANALYSIS_MODEL_SETTINGS)
    assert result.acceptance_criteria_gaps[0].statement.startswith(
        "No acceptance criterion"
    )
    assert result.acceptance_criteria_gaps[0].references == (
        SourceReference("US-1", "user_story"),
    )
    assert result.evidence[0].chunk.content == "Need MFA"


def test_successful_analysis_attaches_ask_result_metadata() -> None:
    """Model-call observability must survive the pack result for composition RunMeta."""
    from domain.models import Usage

    class _MetaChat(_FakeChat):
        def complete(
            self,
            system: str,
            messages: Sequence[Message],
            settings: Mapping[str, object],
        ) -> AskResult:
            self.calls.append((system, messages, settings))
            return AskResult(
                content=self.content,
                model="req-analysis-model",
                latency_ms=33,
                usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                settings=dict(settings),
            )

    use_case = AnalyzeRequirements(
        _RecordingRetrieve([_hit()]), _MetaChat(_analysis_payload())
    )

    result = use_case.execute(_request())

    assert result.ask_result is not None
    assert result.ask_result.model == "req-analysis-model"
    assert result.ask_result.latency_ms == 33
    assert result.ask_result.usage is not None
    assert result.ask_result.usage.total_tokens == 15
    assert result.ask_result.settings == dict(REQUIREMENTS_ANALYSIS_MODEL_SETTINGS)


def test_all_four_structured_sections_are_present_and_independently_parsed() -> None:
    payload = json.dumps(
        {
            "summary": "Cross-source review complete.",
            "acceptance_criteria_gaps": [
                {"statement": "Gap one.", "evidence_ids": ["e0"]}
            ],
            "risks": [{"statement": "Risk one.", "evidence_ids": ["e0"]}],
            "clarification_questions": [
                {"statement": "Question one.", "evidence_ids": ["e0"]}
            ],
        }
    )
    result = AnalyzeRequirements(
        _RecordingRetrieve([_hit()]), _FakeChat(payload)
    ).execute(_request())

    assert result.summary == "Cross-source review complete."
    assert len(result.acceptance_criteria_gaps) == 1
    assert len(result.risks) == 1
    assert len(result.clarification_questions) == 1


def test_empty_sections_retain_retrieved_hits_as_summary_evidence() -> None:
    hits = [
        _hit(content="Need MFA"),
        _hit(source_id="SRS-2", source_type="srs", content="SRS lockout rule"),
    ]
    payload = json.dumps(
        {
            "summary": "No actionable gaps found.",
            "acceptance_criteria_gaps": [],
            "risks": [],
            "clarification_questions": [],
        }
    )
    result = AnalyzeRequirements(
        _RecordingRetrieve(hits), _FakeChat(payload)
    ).execute(_request())

    assert result.acceptance_criteria_gaps == ()
    assert result.risks == ()
    assert result.clarification_questions == ()
    assert {hit.chunk.content for hit in result.evidence} == {
        "Need MFA",
        "SRS lockout rule",
    }


def test_summary_only_evidence_chunks_all_came_from_retrieval() -> None:
    hits = [_hit(content="trusted summary support")]
    result = AnalyzeRequirements(
        _RecordingRetrieve(hits),
        _FakeChat(
            json.dumps(
                {
                    "summary": "Looks complete.",
                    "acceptance_criteria_gaps": [],
                    "risks": [],
                    "clarification_questions": [],
                }
            )
        ),
    ).execute(_request())

    assert {c.chunk.content for c in result.evidence} <= {h.chunk.content for h in hits}


def test_findings_do_not_cite_unrelated_retrieved_hits() -> None:
    hits = [
        _hit(source_id="US-1", source_type="user_story", content="Story MFA"),
        _hit(source_id="SRS-2", source_type="srs", content="SRS lockout"),
    ]
    result = AnalyzeRequirements(
        _RecordingRetrieve(hits),
        _FakeChat(_analysis_payload(evidence_ids=["e0"])),
    ).execute(_request())

    assert len(result.evidence) == 1
    assert result.evidence[0].chunk.content == "Story MFA"
    assert result.evidence[0].chunk.reference == SourceReference("US-1", "user_story")


def test_every_returned_finding_has_at_least_one_trusted_citation() -> None:
    result = AnalyzeRequirements(
        _RecordingRetrieve([_hit()]), _FakeChat(_analysis_payload())
    ).execute(_request())

    for finding in result.acceptance_criteria_gaps:
        assert finding.references
        assert all(isinstance(ref, SourceReference) for ref in finding.references)


def test_empty_retrieval_raises_missing_evidence_before_the_model() -> None:
    retrieve = _RecordingRetrieve([])
    chat = _FakeChat(_analysis_payload())
    use_case = AnalyzeRequirements(retrieve, chat)

    with pytest.raises(MissingEvidenceError):
        use_case.execute(_request())

    assert chat.calls == []


def test_missing_evidence_is_not_reported_as_an_orchestration_error() -> None:
    retrieve = _RecordingRetrieve([])
    chat = _FakeChat(_analysis_payload())
    use_case = AnalyzeRequirements(retrieve, chat)

    with pytest.raises(MissingEvidenceError) as exc_info:
        use_case.execute(_request())

    assert "OrchestrationValidationError" not in type(exc_info.value).__name__
    assert "items must be non-empty" not in str(exc_info.value)


def test_evidence_may_span_multiple_source_kinds_without_story_filtering() -> None:
    hits = [
        _hit(source_type="user_story", source_id="US-1", content="Story MFA"),
        _hit(source_type="srs", source_id="SRS-2", content="SRS MFA lockout"),
        _hit(source_type="openapi", source_id="API-1", content="POST /mfa"),
        _hit(source_type="confluence", source_id="CONF-1", content="Runbook"),
        _hit(source_type="code", source_id="auth.py", content="verify_mfa()"),
    ]
    payload = json.dumps(
        {
            "summary": "Cross-source gaps found.",
            "acceptance_criteria_gaps": [
                {
                    "statement": "SRS lockout missing from story.",
                    "evidence_ids": ["e1"],
                }
            ],
            "risks": [
                {
                    "statement": "OpenAPI lacks rate limit.",
                    "evidence_ids": ["e2"],
                }
            ],
            "clarification_questions": [
                {
                    "statement": "Code path unclear.",
                    "evidence_ids": ["e4"],
                }
            ],
        }
    )
    result = AnalyzeRequirements(_RecordingRetrieve(hits), _FakeChat(payload)).execute(
        _request()
    )

    cited_types = {
        ref.source_type
        for section in (
            result.acceptance_criteria_gaps,
            result.risks,
            result.clarification_questions,
        )
        for finding in section
        for ref in finding.references
    }
    assert cited_types == {"srs", "openapi", "code"}
    assert "user_story" not in cited_types


def test_every_retrieved_source_kind_reaches_the_untrusted_evidence_block() -> None:
    hits = [
        _hit(source_type="user_story", source_id="US-1"),
        _hit(source_type="srs", source_id="SRS-1"),
        _hit(source_type="openapi", source_id="API-1"),
        _hit(source_type="confluence", source_id="CONF-1"),
        _hit(source_type="code", source_id="auth.py"),
    ]
    chat = _FakeChat(_analysis_payload())
    AnalyzeRequirements(_RecordingRetrieve(hits), chat).execute(_request())

    body = chat.calls[0][1][0].content
    payload = json.loads(
        body.split("<<<BEGIN_UNTRUSTED_ASSESSMENT>>>")[1].split(
            "<<<END_UNTRUSTED_ASSESSMENT>>>"
        )[0]
    )
    source_types = {item["source_type"] for item in payload["evidence"]}
    assert source_types == {"user_story", "srs", "openapi", "confluence", "code"}


def test_same_source_id_under_two_kinds_are_separate_catalog_entries() -> None:
    hits = [
        _hit(source_type="user_story", source_id="REQ-1", content="Story text"),
        _hit(source_type="srs", source_id="REQ-1", content="SRS text"),
    ]
    payload = json.dumps(
        {
            "summary": "Both sources differ.",
            "acceptance_criteria_gaps": [
                {
                    "statement": "Story and SRS disagree.",
                    "evidence_ids": ["e0", "e1"],
                }
            ],
            "risks": [],
            "clarification_questions": [],
        }
    )
    result = AnalyzeRequirements(_RecordingRetrieve(hits), _FakeChat(payload)).execute(
        _request()
    )

    refs = result.acceptance_criteria_gaps[0].references
    assert set(refs) == {
        SourceReference("REQ-1", "user_story"),
        SourceReference("REQ-1", "srs"),
    }


@pytest.mark.parametrize(
    "requirements",
    [
        "",
        "   ",
        42,
        "x" * (MAX_REQUIREMENTS_CHARS + 1),
    ],
)
def test_invalid_requirements_reject_before_retrieval_or_model(
    requirements: object,
) -> None:
    retrieve = _RecordingRetrieve([_hit()])
    chat = _FakeChat(_analysis_payload())

    with pytest.raises(RequirementsAnalysisValidationError):
        AnalyzeRequirements(retrieve, chat).execute(
            AnalyzeRequirementsRequest(requirements)  # type: ignore[arg-type]
        )

    assert retrieve.queries == []
    assert chat.calls == []


def test_unknown_evidence_id_is_output_error() -> None:
    chat = _FakeChat(_analysis_payload(evidence_ids=["e99"]))
    with pytest.raises(RequirementsAnalysisOutputError, match="unknown evidence_id"):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), chat).execute(_request())


def test_empty_evidence_ids_is_output_error() -> None:
    payload = json.loads(_analysis_payload())
    payload["acceptance_criteria_gaps"][0]["evidence_ids"] = []
    with pytest.raises(RequirementsAnalysisOutputError, match="evidence_ids must be non-empty"):
        AnalyzeRequirements(
            _RecordingRetrieve([_hit()]), _FakeChat(json.dumps(payload))
        ).execute(_request())


def test_unexpected_root_keys_are_output_error() -> None:
    payload = json.loads(_analysis_payload())
    payload["extra"] = "nope"
    with pytest.raises(RequirementsAnalysisOutputError, match="unexpected model fields"):
        AnalyzeRequirements(
            _RecordingRetrieve([_hit()]), _FakeChat(json.dumps(payload))
        ).execute(_request())


def test_unexpected_finding_keys_are_output_error() -> None:
    payload = json.loads(_analysis_payload())
    payload["acceptance_criteria_gaps"][0]["references"] = [
        {"source_id": "evil", "source_type": "srs"}
    ]
    with pytest.raises(RequirementsAnalysisOutputError, match="unexpected acceptance_criteria_gaps"):
        AnalyzeRequirements(
            _RecordingRetrieve([_hit()]), _FakeChat(json.dumps(payload))
        ).execute(_request())


def test_missing_summary_is_output_error() -> None:
    payload = json.loads(_analysis_payload())
    del payload["summary"]
    with pytest.raises(RequirementsAnalysisOutputError, match="summary is required"):
        AnalyzeRequirements(
            _RecordingRetrieve([_hit()]), _FakeChat(json.dumps(payload))
        ).execute(_request())


def test_missing_section_is_output_error() -> None:
    payload = json.loads(_analysis_payload())
    del payload["risks"]
    with pytest.raises(RequirementsAnalysisOutputError, match="risks is required"):
        AnalyzeRequirements(
            _RecordingRetrieve([_hit()]), _FakeChat(json.dumps(payload))
        ).execute(_request())


def test_non_json_response_is_output_error() -> None:
    with pytest.raises(RequirementsAnalysisOutputError, match="not valid JSON"):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _FakeChat("not-json")).execute(
            _request()
        )


def test_oversized_raw_response_is_output_error() -> None:
    chat = _FakeChat("x" * (MAX_MODEL_RESPONSE_CHARS + 1))
    with pytest.raises(RequirementsAnalysisOutputError, match="model response"):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), chat).execute(_request())


def test_provider_error_propagates_unchanged() -> None:
    class _Boom(_FakeChat):
        def complete(self, system, messages, settings):  # type: ignore[no-untyped-def]
            raise ProviderError("vendor outage")

    with pytest.raises(ProviderError, match="vendor outage") as captured:
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _Boom("")).execute(_request())
    assert captured.value.__cause__ is None


def test_model_supplied_references_are_rejected() -> None:
    payload = json.loads(_analysis_payload())
    payload["acceptance_criteria_gaps"][0]["references"] = [
        {"source_id": "evil", "source_type": "srs"}
    ]
    with pytest.raises(RequirementsAnalysisOutputError, match="unexpected acceptance_criteria_gaps"):
        AnalyzeRequirements(
            _RecordingRetrieve([_hit()]), _FakeChat(json.dumps(payload))
        ).execute(_request())


def test_every_cited_chunk_came_from_retrieval() -> None:
    hits = [_hit(content="trusted only")]
    result = AnalyzeRequirements(
        _RecordingRetrieve(hits), _FakeChat(_analysis_payload())
    ).execute(_request())
    assert {c.chunk.content for c in result.evidence} <= {h.chunk.content for h in hits}


def test_caller_validation_is_domain_validation_not_tool_argument() -> None:
    assert issubclass(RequirementsAnalysisValidationError, DomainValidationError)
    assert not issubclass(
        RequirementsAnalysisValidationError, ToolArgumentValidationError
    )


def test_invalid_model_output_is_provider_error_subtype_not_tool_failure() -> None:
    from domain.errors import ToolFailureError

    assert issubclass(RequirementsAnalysisOutputError, ProviderError)
    assert not issubclass(RequirementsAnalysisOutputError, ToolFailureError)
    with pytest.raises(RequirementsAnalysisOutputError):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _FakeChat("not-json")).execute(
            _request()
        )


def test_provider_error_from_chat_port_is_not_output_error_wrapper() -> None:
    class _Boom(_FakeChat):
        def complete(self, system, messages, settings):  # type: ignore[no-untyped-def]
            raise ProviderError("vendor outage")

    with pytest.raises(ProviderError) as captured:
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _Boom("")).execute(_request())

    assert type(captured.value) is ProviderError
    assert not isinstance(captured.value, RequirementsAnalysisOutputError)
