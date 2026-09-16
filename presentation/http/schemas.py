"""OpenAPI / wire schemas for the HTTP presentation adapter."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from application.contracts import (
    Citation,
    ConnectorSyncResponse,
    InvokeToolResponse,
    RunMeta,
)
from composition.software_delivery_tools import SoftwareDeliveryRunView
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    DocumentChunk,
    SourceReference,
    SourceType,
)


class HubSourceType(StrEnum):
    """Hub catalog kinds accepted by chunk-inspect query params.

    Mirrors ``domain.knowledge.HUB_SOURCE_TYPES`` as a named OpenAPI schema so
    the wire contract stays documented and does not silently widen with
    ``SourceType``.
    """

    KNOWLEDGE_DOCUMENT = SourceType.KNOWLEDGE_DOCUMENT
    GOOGLE_DRIVE = SourceType.GOOGLE_DRIVE
    GITHUB = SourceType.GITHUB


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
    short_term_memory_enabled: bool = False


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


class GitHubLastSyncResponse(BaseModel):
    """Last GitHub user-OAuth sync summary. Counts are honest; no secrets."""

    synced_at: str
    new_count: int
    updated_count: int
    unchanged_count: int
    removed_count: int
    failed_count: int


class GitHubStatusResponse(BaseModel):
    """GitHub connector presence and user OAuth connection (no secrets)."""

    configured: bool
    available: bool
    connected: bool = False
    oauth_ready: bool = False
    account_login: str | None = None
    document_count: int = 0
    owner: str | None = None
    repo: str | None = None
    project_owner: str | None = None
    project_number: int | None = None
    last_sync: GitHubLastSyncResponse | None = None
    reauthorization_required: bool = False
    connection_state: str = "disconnected"
    sync_scope: str | None = None
    setup_required: bool = False


class GitHubRepoItemResponse(BaseModel):
    """One repository row for the Hub picker."""

    owner: str
    name: str
    full_name: str
    private: bool = False


class GitHubRepoPageResponse(BaseModel):
    """One page of repositories for the Hub picker."""

    items: list[GitHubRepoItemResponse]
    has_next: bool = False
    page: int = 1


class GitHubProjectItemResponse(BaseModel):
    """One ProjectV2 row for the Hub picker."""

    owner_login: str
    number: int
    title: str


class GitHubProjectPageResponse(BaseModel):
    """One page of ProjectV2 projects for the Hub picker."""

    items: list[GitHubProjectItemResponse]
    next_cursor: str | None = None


class GitHubSelectionResponse(BaseModel):
    """Saved Hub sync targets (no tokens)."""

    owner: str | None = None
    repo: str | None = None
    project_owner: str | None = None
    project_number: int | None = None
    connector_id: str | None = None


class GitHubSelectionRequest(BaseModel):
    """Replace the saved GitHub sync selection."""

    owner: str | None = None
    repo: str | None = None
    project_owner: str | None = None
    project_number: int | None = None


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


class GoogleDriveCreateFolderRequest(BaseModel):
    """Create a Drive folder under an existing parent (or My Drive)."""

    name: str = Field(min_length=1, max_length=256)
    parent_id: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^(root|[A-Za-z0-9_-]{1,128})$",
    )


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
    status: Literal["ingested", "updated", "skipped", "failed", "removed"]
    chunk_count: int
    error_type: str | None = None


class GoogleDriveSyncResponse(BaseModel):
    """Projected connector sync counts and per-document outcomes."""

    ingested_count: int
    updated_count: int = 0
    skipped_count: int
    failed_count: int
    removed_count: int = 0
    outcomes: list[ConnectorSyncOutcomeResponse]


class GitHubSyncResponse(GoogleDriveSyncResponse):
    """Projected GitHub sync counts and per-document outcomes."""


def connector_sync_response(
    response: ConnectorSyncResponse,
) -> GoogleDriveSyncResponse:
    """Project application sync counts onto the wire schema."""
    return GoogleDriveSyncResponse(
        ingested_count=response.ingested_count,
        updated_count=response.updated_count,
        skipped_count=response.skipped_count,
        failed_count=response.failed_count,
        removed_count=response.removed_count,
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


def google_drive_sync_response(
    response: ConnectorSyncResponse,
) -> GoogleDriveSyncResponse:
    """Project Drive sync counts onto the wire schema."""
    return connector_sync_response(response)


def github_sync_response(response: ConnectorSyncResponse) -> GitHubSyncResponse:
    """Project GitHub sync counts onto the wire schema."""
    base = connector_sync_response(response)
    return GitHubSyncResponse(**base.model_dump())


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


class SourceLocatorRequest(BaseModel):
    """Provider-neutral live source locator for chat handoff / create."""

    provider: str = Field(min_length=1)
    locator: str = Field(min_length=1)


class SourceReferenceRequest(BaseModel):
    """Explicit source identity retained for draft projections."""

    source_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)


class ChatAskRequest(BaseModel):
    """Wire body for ``POST /api/v1/chat/ask``."""

    query: str = Field(min_length=1)
    history: list[ChatHistoryMessage] = Field(default_factory=list)
    runtime: ChatRuntimeRequest | None = None
    conversation_id: str | None = None
    source_locator: SourceLocatorRequest | None = None


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
    export_destination_required: bool = False
    drive_file_id: str = ""
    drive_file_name: str = ""


class ChatWorkflowActionResponse(BaseModel):
    """Allowlisted chat handoff action (never inferred from prose alone)."""

    kind: Literal["start_workflow", "open_workflow"]
    workflow_id: str
    label: str
    source_locator: SourceLocatorRequest | None = None
    draft_id: str | None = None


class ChatAskResponse(BaseModel):
    """Successful grounded ask turn."""

    answer: str
    citations: list[CitationResponse]
    tools_used: list[ToolUsedResponse]
    run: RunMetaResponse | None = None
    tool_run: ToolRunResponse | None = None
    action: ChatWorkflowActionResponse | None = None
    pending_approval: PendingToolApprovalResponse | None = None


class PendingToolApprovalResponse(BaseModel):
    """Safe HITL projection; never includes raw Tool arguments or secrets."""

    approval_id: str
    tool_name: str
    title: str
    summary: str
    status: str = "pending"
    destination_label: str | None = None
    file_name: str | None = None
    selected_title_count: int | None = None


class ToolApprovalDecisionRequest(BaseModel):
    """Wire body for approving or rejecting a pending tool call."""

    decision: Literal["approve", "reject"]


class ToolApprovalDecisionResponse(BaseModel):
    """Result after resuming a pending tool approval."""

    answer: str
    cancelled: bool = False
    pending_approval: PendingToolApprovalResponse | None = None
    tool_run: ToolRunResponse | None = None


class TestCandidateResponse(BaseModel):
    """One coverage candidate on a test-design draft."""

    candidate_id: str
    title: str
    category: str
    rationale: str
    evidence_references: list[SourceReferenceResponse]
    selected: bool
    origin: str


class CoverageGapResponse(BaseModel):
    """Typed coverage gap where evidence does not support a category.

    Kept on ``/api/v1`` as an empty list for backward compatibility after the
    workspace stopped emitting gaps; drop in ``/api/v2``.
    """

    category: str
    detail: str


class TestCoverageDraftResponse(BaseModel):
    """Workspace-scoped test-design draft."""

    draft_id: str
    workspace_id: str
    conversation_id: str
    source_reference: SourceReferenceResponse
    ticket_identifier: str
    status: str
    candidates: list[TestCandidateResponse]
    coverage_gaps: list[CoverageGapResponse]
    version: int
    selected_candidate_ids: list[str]


class CreateTestDesignDraftRequest(BaseModel):
    """Wire body for ``POST /api/v1/test-design/drafts``."""

    conversation_id: str = Field(min_length=1)
    source_locator: SourceLocatorRequest


class PatchTestDesignDraftRequest(BaseModel):
    """Wire body for ``PATCH /api/v1/test-design/drafts/{draft_id}``."""

    expected_version: int = Field(ge=1)
    candidates: list[TestCandidateResponse] | None = None


class ExpectedVersionRequest(BaseModel):
    """Mutating body that only carries compare-and-swap version."""

    expected_version: int = Field(ge=1)


class ExportTestDesignGoogleDriveRequest(BaseModel):
    """Wire body for ``POST /api/v1/test-design/drafts/{draft_id}/export/google-drive``."""

    folder_id: str = Field(min_length=1, max_length=128)
    file_name: str | None = Field(default=None, max_length=255)
    destination_label: str | None = Field(default=None, max_length=255)


class ExportTestDesignGoogleDriveResponse(BaseModel):
    """Safe receipt after exporting selected titles to Google Drive."""

    file_id: str
    file_name: str


class ChatExportDestinationRequest(BaseModel):
    """Persist a Drive folder for chat agent export / HITL prepare."""

    folder_id: str = Field(min_length=1, max_length=128)
    destination_label: str | None = Field(default=None, max_length=255)


class ChatExportDestinationResponse(BaseModel):
    """Confirmation after saving an export destination (no folder id echo)."""

    destination_label: str


def chat_workflow_action_response(
    view: object,
) -> ChatWorkflowActionResponse:
    """Project a composition chat action view onto the wire schema."""
    locator = getattr(view, "source_locator", None)
    return ChatWorkflowActionResponse(
        kind=view.kind,  # type: ignore[attr-defined]
        workflow_id=view.workflow_id,  # type: ignore[attr-defined]
        label=view.label,  # type: ignore[attr-defined]
        source_locator=(
            None
            if locator is None
            else SourceLocatorRequest(
                provider=locator.provider,
                locator=locator.locator,
            )
        ),
        draft_id=getattr(view, "draft_id", None),
    )


def test_coverage_draft_response(view: object) -> TestCoverageDraftResponse:
    """Project a composition draft view onto the wire schema."""
    source = view.source_reference  # type: ignore[attr-defined]
    return TestCoverageDraftResponse(
        draft_id=view.draft_id,  # type: ignore[attr-defined]
        workspace_id=view.workspace_id,  # type: ignore[attr-defined]
        conversation_id=view.conversation_id,  # type: ignore[attr-defined]
        source_reference=SourceReferenceResponse(
            source_id=source.source_id,
            source_type=source.source_type,
        ),
        ticket_identifier=view.ticket_identifier,  # type: ignore[attr-defined]
        status=view.status,  # type: ignore[attr-defined]
        candidates=[
            TestCandidateResponse(
                candidate_id=item.candidate_id,
                title=item.title,
                category=item.category,
                rationale=item.rationale,
                evidence_references=[
                    SourceReferenceResponse(
                        source_id=ref.source_id, source_type=ref.source_type
                    )
                    for ref in item.evidence_references
                ],
                selected=item.selected,
                origin=item.origin,
            )
            for item in view.candidates  # type: ignore[attr-defined]
        ],
        coverage_gaps=[],
        version=view.version,  # type: ignore[attr-defined]
        selected_candidate_ids=list(view.selected_candidate_ids),  # type: ignore[attr-defined]
    )


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
        export_destination_required=bool(view.export_destination_required),
        drive_file_id=view.drive_file_id or "",
        drive_file_name=view.drive_file_name or "",
    )


def pending_tool_approval_response(
    pending: object | None,
) -> PendingToolApprovalResponse | None:
    """Project a domain/application pending approval onto the wire schema."""
    if pending is None:
        return None
    return PendingToolApprovalResponse(
        approval_id=str(getattr(pending, "approval_id")),
        tool_name=str(getattr(pending, "tool_name")),
        title=str(getattr(pending, "title")),
        summary=str(getattr(pending, "summary")),
        status=str(getattr(pending, "status", "pending") or "pending"),
        destination_label=getattr(pending, "destination_label", None),
        file_name=getattr(pending, "file_name", None),
        selected_title_count=getattr(pending, "selected_title_count", None),
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

_MISSING_BLOB_SUMMARY = (
    "Original file bytes are not stored; preview and download are unavailable. "
    "Replace the document to restore them."
)

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
    has_stored_content: bool = True


class DocumentListResponse(BaseModel):
    """Uploaded-document catalog for the documents UI."""

    documents: list[CatalogDocumentResponse]


class DocumentChunkResponse(BaseModel):
    """Wire projection of one stored chunk for the documents UI.

    Scalar fields are an explicit allowlist. ``extra`` forwards connector
    metadata from ``SourceMetadata.extra`` without a key filter — callers must
    not treat it as a closed schema.
    """

    index: int
    content: str
    source_id: str
    source_type: str
    title: str | None = None
    provider: str | None = None
    content_format: str | None = None
    extra: dict[str, str]


class DocumentChunkListResponse(BaseModel):
    """Stored chunks for one catalogued document."""

    chunks: list[DocumentChunkResponse]
    has_more: bool


def catalog_document_response(document: CatalogDocument) -> CatalogDocumentResponse:
    """Project a catalog row; never serialize raw adapter ``error`` text."""
    from application.manage_documents import MISSING_UPLOAD_BLOB_ERROR

    missing_blob = MISSING_UPLOAD_BLOB_ERROR in (document.error or "")
    if missing_blob and document.status is CatalogStatus.READY:
        summary: str | None = _MISSING_BLOB_SUMMARY
        has_error = True
    else:
        summary = (
            _DRIVE_ERROR_SUMMARY_BY_STATUS.get(document.status)
            if document.reference.source_type == SourceType.GOOGLE_DRIVE
            else _ERROR_SUMMARY_BY_STATUS.get(document.status)
        )
        has_error = document.status in {
            CatalogStatus.FAILED,
            CatalogStatus.DEGRADED,
        }
    has_stored_content = (
        document.reference.source_type == SourceType.KNOWLEDGE_DOCUMENT
        and not missing_blob
        and document.status is not CatalogStatus.PENDING
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
        has_error=has_error,
        error_summary=summary,
        has_stored_content=has_stored_content,
    )


def document_chunk_response(chunk: DocumentChunk) -> DocumentChunkResponse:
    """Project a stored chunk to the wire fields used by the documents UI."""
    return DocumentChunkResponse(
        index=chunk.index,
        content=chunk.content,
        source_id=chunk.reference.source_id,
        source_type=chunk.reference.source_type,
        title=chunk.metadata.title,
        provider=chunk.metadata.provider,
        content_format=chunk.metadata.content_format,
        extra=dict(chunk.metadata.extra),
    )

