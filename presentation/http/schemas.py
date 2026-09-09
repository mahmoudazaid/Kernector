"""OpenAPI / wire schemas for the HTTP presentation adapter."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from application.contracts import (
    Citation,
    ConnectorSyncResponse,
    InvokeToolResponse,
    RunMeta,
)
from composition.software_delivery_tools import SoftwareDeliveryRunView
from domain.knowledge import CatalogDocument, CatalogStatus, SourceReference, SourceType


class HealthResponse(BaseModel):
    """Operational readiness payload for unversioned ``GET /health``."""

    status: str = Field(examples=["ok"])


class OpenRouterSettingsResponse(BaseModel):
    """OpenRouter models and default from runtime config."""

    models: list[str]
    default_model: str | None = None


class OllamaSettingsResponse(BaseModel):
    """Ollama defaults from runtime config (live models come from probe)."""

    default_base_url: str | None = None
    default_model: str | None = None


class ModelSettingDefResponse(BaseModel):
    """One generation setting for Settings UI controls."""

    key: str
    label: str
    widget: str
    default: float | int
    min_value: float | int
    max_value: float | int
    step: float | int
    help: str
    providers: list[str]


class RuntimeConstraintsResponse(BaseModel):
    """Global server-enforced constraints for client preflight validation."""

    max_input_length: int
    max_upload_bytes: int
    supported_upload_suffixes: list[str]


class RuntimeSettingsResponse(BaseModel):
    """Client-facing runtime contract: providers, packs, and constraints."""

    providers: list[str]
    default_provider: str
    openrouter: OpenRouterSettingsResponse
    ollama: OllamaSettingsResponse
    model_settings: list[ModelSettingDefResponse]
    enabled_packs: list[str]
    constraints: RuntimeConstraintsResponse


class OllamaStatusResponse(BaseModel):
    """Ollama reachability and installed models for a base URL."""

    reachable: bool
    models: list[str]


class GoogleDriveLastSyncResponse(BaseModel):
    """Last user-OAuth sync summary. Counts are honest; no secrets."""

    synced_at: str
    new_count: int
    updated_count: int
    unchanged_count: int
    failed_count: int


class GoogleDriveStatusResponse(BaseModel):
    """Google Drive connector presence and user OAuth connection (no secrets)."""

    configured: bool
    available: bool
    connected: bool = False
    oauth_ready: bool = False
    account_email: str | None = None
    document_count: int = 0
    folder_count: int | None = None
    last_sync: GoogleDriveLastSyncResponse | None = None
    reauthorization_required: bool = False
    setup_required: bool = False
    connection_state: str = "disconnected"
    sync_scope: str | None = None


class GoogleDriveBrowseItemResponse(BaseModel):
    """One Drive picker row. ``id`` is the only identity field."""

    id: str
    name: str
    kind: str
    mime_type: str | None = None
    supported: bool
    modified_at: str | None = None


class GoogleDriveBrowsePageResponse(BaseModel):
    """One page of Drive picker results. Tokens stay off this payload."""

    items: list[GoogleDriveBrowseItemResponse]
    next_page_token: str | None = None


class GoogleDriveSelectedItemResponse(BaseModel):
    """Saved sync root: Drive ID plus a presentation name."""

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1)


class GoogleDriveSelectedItemRequest(BaseModel):
    """PUT selection item. ``root`` is rejected so sync cannot cover all Drive."""

    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    name: str = Field(min_length=1, max_length=256)

    @field_validator("id")
    @classmethod
    def reject_my_drive_root(cls, value: str) -> str:
        if value == "root":
            raise ValueError("Drive selection cannot use the My Drive root")
        return value


GOOGLE_DRIVE_SELECTION_LIST_MAX = 100


class GoogleDriveSelectionResponse(BaseModel):
    """Saved folder and exact-file roots. Unbounded so existing grants still load."""

    folders: list[GoogleDriveSelectedItemResponse] = Field(default_factory=list)
    files: list[GoogleDriveSelectedItemResponse] = Field(default_factory=list)


class GoogleDriveSelectionRequest(BaseModel):
    """PUT body: bounded so one request can finish inside the client timeout."""

    folders: list[GoogleDriveSelectedItemRequest] = Field(
        default_factory=list, max_length=GOOGLE_DRIVE_SELECTION_LIST_MAX
    )
    files: list[GoogleDriveSelectedItemRequest] = Field(
        default_factory=list, max_length=GOOGLE_DRIVE_SELECTION_LIST_MAX
    )


class ConnectorSyncOutcomeResponse(BaseModel):
    """One listed Drive document outcome from a sync run."""

    source_id: str
    status: Literal["ingested", "skipped", "failed"]
    chunk_count: int
    error_type: str | None = None


class GoogleDriveSyncResponse(BaseModel):
    """Projected connector sync counts and per-document outcomes."""

    ingested_count: int
    skipped_count: int
    failed_count: int
    outcomes: list[ConnectorSyncOutcomeResponse]


def google_drive_sync_response(
    response: ConnectorSyncResponse,
) -> GoogleDriveSyncResponse:
    """Project application sync counts onto the wire schema."""
    return GoogleDriveSyncResponse(
        ingested_count=response.ingested_count,
        skipped_count=response.skipped_count,
        failed_count=response.failed_count,
        outcomes=[
            ConnectorSyncOutcomeResponse(
                source_id=outcome.source_id,
                status=outcome.status.value,
                chunk_count=outcome.chunk_count,
                error_type=outcome.error_type,
            )
            for outcome in response.outcomes
        ],
    )


class ChatHistoryMessage(BaseModel):
    """One prior conversation turn for grounded ask."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRuntimeRequest(BaseModel):
    """Optional client runtime overrides from Settings localStorage (#237)."""

    provider: Literal["openrouter", "ollama"] | None = None
    model: str | None = None
    ollama_base_url: str | None = None
    settings: dict[str, int | float] = Field(default_factory=dict)


class ChatAskRequest(BaseModel):
    """Wire body for ``POST /api/v1/chat/ask``."""

    query: str = Field(min_length=1)
    history: list[ChatHistoryMessage] = Field(default_factory=list)
    runtime: ChatRuntimeRequest | None = None


class CitationResponse(BaseModel):
    """Provenance pointer on a grounded answer."""

    source_id: str
    source_type: str
    quote: str | None = None
    chunk_index: int | None = None


class ToolUsedResponse(BaseModel):
    """Opaque tool contribution measured by character count only."""

    tool_name: str
    result_chars: int


class RunMetaResponse(BaseModel):
    """Safe run fields the chat UI may display (allowlisted projection)."""

    request_id: str | None = None
    outcome: str | None = None
    latency_ms: int | None = None
    model: str | None = None
    total_tokens: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    pack: str | None = None
    query_rewritten: bool | None = None
    hit_count: int | None = None
    citation_count: int | None = None
    tools: list[str] = Field(default_factory=list)


class ToolCallResponse(BaseModel):
    """One projected tool invocation (authored summary, never opaque payload)."""

    tool_name: str
    ok: bool
    summary: str = ""


class SourceReferenceResponse(BaseModel):
    """Provenance id/type for projected tool results."""

    source_id: str
    source_type: str


class RiskFactorResponse(BaseModel):
    """One risk factor with provenance ids only."""

    factor_id: str
    weight: int
    references: list[SourceReferenceResponse]


class RiskScoreResponse(BaseModel):
    """Structured risk assessment for the chat UI."""

    score: int
    level: str
    rationale: str
    factors: list[RiskFactorResponse]


class TestCaseResponse(BaseModel):
    """One generated test case."""

    title: str
    steps: list[str]
    expected: str
    references: list[SourceReferenceResponse]


class TestCasesResponse(BaseModel):
    """Generated test cases for the chat UI."""

    output_style: str
    cases: list[TestCaseResponse]


class ToolRunResponse(BaseModel):
    """Projected Software Delivery tool-run view (no opaque payloads)."""

    summary: str
    calls: list[ToolCallResponse]
    risk: RiskScoreResponse | None = None
    test_cases: TestCasesResponse | None = None
    markdown: str = ""


class ChatAskResponse(BaseModel):
    """Successful grounded ask turn."""

    answer: str
    citations: list[CitationResponse]
    tools_used: list[ToolUsedResponse]
    run: RunMetaResponse | None = None
    tool_run: ToolRunResponse | None = None


def citation_response(citation: Citation) -> CitationResponse:
    """Project an application citation onto the wire schema."""
    return CitationResponse(
        source_id=citation.reference.source_id,
        source_type=citation.reference.source_type,
        quote=citation.quote,
        chunk_index=citation.chunk_index,
    )


def tools_used_response(
    tool_outputs: Sequence[InvokeToolResponse],
) -> list[ToolUsedResponse]:
    """Measure opaque tool payloads; never serialize ``result`` text."""
    return [
        ToolUsedResponse(tool_name=output.tool_name, result_chars=len(output.result))
        for output in tool_outputs
    ]


def run_meta_response(run: RunMeta | None) -> RunMetaResponse | None:
    """Project ``RunMeta`` fields the chat UI may show.

    Excludes ``settings``, ``error_type``, and ``source_type``.
    """
    if run is None:
        return None
    usage = run.usage
    return RunMetaResponse(
        request_id=run.request_id,
        outcome=run.outcome,
        latency_ms=run.latency_ms,
        model=run.model,
        total_tokens=None if usage is None else usage.total_tokens,
        prompt_tokens=None if usage is None else usage.prompt_tokens,
        completion_tokens=None if usage is None else usage.completion_tokens,
        pack=run.pack,
        query_rewritten=run.query_rewritten,
        hit_count=run.hit_count,
        citation_count=run.citation_count,
        tools=list(run.tools),
    )


def _source_refs(
    references: Sequence[SourceReference],
) -> list[SourceReferenceResponse]:
    return [
        SourceReferenceResponse(
            source_id=ref.source_id, source_type=ref.source_type
        )
        for ref in references
    ]


def tool_run_response(view: SoftwareDeliveryRunView) -> ToolRunResponse:
    """Project a typed Software Delivery view; opaque payloads stay out."""
    risk = None
    if view.risk is not None:
        risk = RiskScoreResponse(
            score=view.risk.score,
            level=view.risk.level,
            rationale=view.risk.rationale,
            factors=[
                RiskFactorResponse(
                    factor_id=factor.factor_id,
                    weight=factor.weight,
                    references=_source_refs(factor.references),
                )
                for factor in view.risk.factors
            ],
        )
    test_cases = None
    if view.test_cases is not None:
        test_cases = TestCasesResponse(
            output_style=view.test_cases.output_style,
            cases=[
                TestCaseResponse(
                    title=case.title,
                    steps=list(case.steps),
                    expected=case.expected,
                    references=_source_refs(case.references),
                )
                for case in view.test_cases.cases
            ],
        )
    return ToolRunResponse(
        summary=view.summary,
        calls=[
            ToolCallResponse(
                tool_name=call.tool_name, ok=call.ok, summary=call.summary
            )
            for call in view.calls
        ],
        risk=risk,
        test_cases=test_cases,
        markdown=view.markdown,
    )


_ERROR_SUMMARY_BY_STATUS: dict[CatalogStatus, str] = {
    CatalogStatus.FAILED: (
        "Ingestion failed for this document. Delete it and upload again."
    ),
    CatalogStatus.DEGRADED: (
        "Ingestion did not finish cleanly; some chunks may be stored. "
        "Replace or delete this document."
    ),
}

_DRIVE_ERROR_SUMMARY_BY_STATUS: dict[CatalogStatus, str] = {
    CatalogStatus.FAILED: (
        "This Google Drive file could not be indexed. Sync again or remove it in Browse."
    ),
    CatalogStatus.DEGRADED: (
        "Indexing did not finish cleanly. Sync again or remove it in Browse."
    ),
}


class CatalogDocumentResponse(BaseModel):
    """Wire projection of one uploaded catalog row (sanitized diagnostics)."""

    source_id: str
    source_type: str
    file_name: str
    title: str | None = None
    content_format: str | None = None
    status: Literal["pending", "ready", "failed", "degraded"]
    uploaded_at: str
    chunk_count: int
    has_error: bool
    error_summary: str | None = None


class DocumentListResponse(BaseModel):
    """Uploaded-document catalog for the documents UI."""

    documents: list[CatalogDocumentResponse]


def catalog_document_response(document: CatalogDocument) -> CatalogDocumentResponse:
    """Project a catalog row; never serialize raw adapter ``error`` text."""
    summary = (
        _DRIVE_ERROR_SUMMARY_BY_STATUS.get(document.status)
        if document.reference.source_type == SourceType.GOOGLE_DRIVE
        else _ERROR_SUMMARY_BY_STATUS.get(document.status)
    )
    return CatalogDocumentResponse(
        source_id=document.reference.source_id,
        source_type=document.reference.source_type,
        file_name=document.file_name,
        title=document.title,
        content_format=document.content_format,
        status=document.status.value,
        uploaded_at=document.uploaded_at.isoformat(),
        chunk_count=document.chunk_count,
        has_error=document.status
        in {CatalogStatus.FAILED, CatalogStatus.DEGRADED},
        error_summary=summary,
    )

