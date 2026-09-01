"""Tests for ChatModel-backed requirements analysis."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest

from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
)
from domain.models import AskResult, Message
from domain.errors import ProviderError, ToolFailureError
from packs.software_delivery.errors import (
    MissingEvidenceError,
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


def _analysis_payload(*, evidence_ids: list[str] | None = None) -> str:
    return json.dumps(
        {
            "answer": "MFA is required but lockout rules are unclear.",
            "findings": [
                {
                    "category": "gap",
                    "statement": "No acceptance criterion covers lockout after failed MFA.",
                    "evidence_ids": evidence_ids or ["e0"],
                }
            ],
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
    assert result.findings[0].category == "gap"
    assert result.findings[0].references == (SourceReference("US-1", "user_story"),)
    assert result.evidence[0].chunk.content == "Need MFA"


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
            "answer": "Cross-source gaps found.",
            "findings": [
                {
                    "category": "gap",
                    "statement": "SRS lockout missing from story.",
                    "evidence_ids": ["e1"],
                },
                {
                    "category": "risk",
                    "statement": "OpenAPI lacks rate limit.",
                    "evidence_ids": ["e2"],
                },
                {
                    "category": "clarification",
                    "statement": "Code path unclear.",
                    "evidence_ids": ["e4"],
                },
            ],
        }
    )
    retrieve = _RecordingRetrieve(hits)
    chat = _FakeChat(payload)
    result = AnalyzeRequirements(retrieve, chat).execute(_request())

    cited_types = {ref.source_type for f in result.findings for ref in f.references}
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
    retrieve = _RecordingRetrieve(hits)
    chat = _FakeChat(_analysis_payload())
    AnalyzeRequirements(retrieve, chat).execute(_request())

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
            "answer": "Both sources differ.",
            "findings": [
                {
                    "category": "ambiguity",
                    "statement": "Story and SRS disagree.",
                    "evidence_ids": ["e0", "e1"],
                }
            ],
        }
    )
    retrieve = _RecordingRetrieve(hits)
    chat = _FakeChat(payload)
    result = AnalyzeRequirements(retrieve, chat).execute(_request())

    refs = result.findings[0].references
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


def test_unknown_evidence_id_is_tool_failure() -> None:
    chat = _FakeChat(_analysis_payload(evidence_ids=["e99"]))
    with pytest.raises(ToolFailureError, match="unknown evidence_id"):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), chat).execute(_request())


def test_empty_evidence_ids_is_tool_failure() -> None:
    payload = json.loads(_analysis_payload())
    payload["findings"][0]["evidence_ids"] = []
    with pytest.raises(ToolFailureError, match="evidence_ids must be non-empty"):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _FakeChat(json.dumps(payload))).execute(
            _request()
        )


def test_unknown_category_is_tool_failure() -> None:
    payload = json.loads(_analysis_payload())
    payload["findings"][0]["category"] = "unknown"
    with pytest.raises(ToolFailureError, match="category"):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _FakeChat(json.dumps(payload))).execute(
            _request()
        )


def test_unexpected_root_keys_are_tool_failure() -> None:
    payload = json.loads(_analysis_payload())
    payload["extra"] = "nope"
    with pytest.raises(ToolFailureError, match="unexpected model fields"):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _FakeChat(json.dumps(payload))).execute(
            _request()
        )


def test_unexpected_finding_keys_are_tool_failure() -> None:
    payload = json.loads(_analysis_payload())
    payload["findings"][0]["references"] = [
        {"source_id": "evil", "source_type": "srs"}
    ]
    with pytest.raises(ToolFailureError, match="unexpected finding fields"):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _FakeChat(json.dumps(payload))).execute(
            _request()
        )


def test_missing_answer_is_tool_failure() -> None:
    payload = json.loads(_analysis_payload())
    del payload["answer"]
    with pytest.raises(ToolFailureError, match="answer is required"):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _FakeChat(json.dumps(payload))).execute(
            _request()
        )


def test_missing_findings_is_tool_failure() -> None:
    payload = json.loads(_analysis_payload())
    del payload["findings"]
    with pytest.raises(ToolFailureError, match="findings is required"):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _FakeChat(json.dumps(payload))).execute(
            _request()
        )


def test_non_json_response_is_tool_failure() -> None:
    with pytest.raises(ToolFailureError, match="not valid JSON"):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _FakeChat("not-json")).execute(
            _request()
        )


def test_oversized_raw_response_is_tool_failure() -> None:
    chat = _FakeChat("x" * (MAX_MODEL_RESPONSE_CHARS + 1))
    with pytest.raises(ToolFailureError, match="model response"):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), chat).execute(_request())


def test_provider_error_maps_to_tool_failure_with_cause() -> None:
    class _Boom(_FakeChat):
        def complete(self, system, messages, settings):  # type: ignore[no-untyped-def]
            raise ProviderError("vendor")

    with pytest.raises(ToolFailureError) as captured:
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _Boom("")).execute(_request())
    assert isinstance(captured.value.__cause__, ProviderError)


def test_model_supplied_references_are_rejected() -> None:
    payload = json.loads(_analysis_payload())
    payload["findings"][0]["references"] = [
        {"source_id": "evil", "source_type": "srs"}
    ]
    with pytest.raises(ToolFailureError, match="unexpected finding fields"):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _FakeChat(json.dumps(payload))).execute(
            _request()
        )


def test_every_cited_chunk_came_from_retrieval() -> None:
    hits = [_hit(content="trusted only")]
    result = AnalyzeRequirements(
        _RecordingRetrieve(hits), _FakeChat(_analysis_payload())
    ).execute(_request())
    assert {c.chunk.content for c in result.evidence} <= {h.chunk.content for h in hits}


def test_invalid_model_output_is_not_caller_validation() -> None:
    with pytest.raises(ToolFailureError):
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _FakeChat("not-json")).execute(
            _request()
        )
    try:
        AnalyzeRequirements(_RecordingRetrieve([_hit()]), _FakeChat("{}")).execute(
            _request()
        )
    except RequirementsAnalysisValidationError:
        pytest.fail(
            "model output must not raise RequirementsAnalysisValidationError"
        )
    except ToolFailureError:
        pass




