"""OpenAPI / wire schemas for the HTTP presentation adapter."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.contracts import (
    Citation,
    ConnectorSyncResponse,
    InvokeToolResponse,
    RunMeta,
)
from composition.software_delivery.tools import SoftwareDeliveryRunView
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    DocumentChunk,
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
    JIRA = SourceType.JIRA


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


class JiraSiteResponse(BaseModel):
    """One Jira instance; ``cloud_id`` mirrors ``instance_id`` for Data Center / Server."""

    cloud_id: str
    instance_id: str
    name: str
    url: str


class JiraSiteListResponse(BaseModel):
    """Jira sites for the Hub site step."""

    items: list[JiraSiteResponse]


class JiraSiteRequest(BaseModel):
    """Select one Jira site by Atlassian cloud id."""

    cloud_id: str = Field(min_length=1, max_length=128)


class JiraLastSyncResponse(GitHubLastSyncResponse):
    """Last Jira sync summary. Counts are honest; no secrets."""


class JiraStatusResponse(BaseModel):
    """Jira connection, selected site and projects (no secrets)."""

    mode: Literal["cloud", "data_center"] = "cloud"
    available: bool
    oauth_ready: bool
    connected: bool = False
    account_name: str | None = None
    site: JiraSiteResponse | None = None
    project_keys: list[str] = Field(default_factory=list)
    document_count: int = 0
    last_sync: JiraLastSyncResponse | None = None
    reauthorization_required: bool = False
    setup_required: bool = False
    connection_state: Literal[
        "disconnected",
        "site_selection_required",
        "setup_required",
        "ready",
        "reauthorization_required",
    ] = "disconnected"
    sync_scope: str | None = None


class JiraProjectItemResponse(BaseModel):
    """One Jira project row for the Hub picker."""

    key: str
    name: str


class JiraProjectPageResponse(BaseModel):
    """One page of Jira projects; ``next_start_at`` is null on the last page."""

    items: list[JiraProjectItemResponse]
    next_start_at: int | None = None


JIRA_SELECTION_LIST_MAX = 100


class JiraSelectionResponse(BaseModel):
    """Saved Jira site and project keys (no tokens)."""

    site: JiraSiteResponse | None = None
    project_keys: list[str] = Field(default_factory=list)
    connector_id: str | None = None


class JiraSelectionRequest(BaseModel):
    """Replace the saved project keys on the selected site."""

    project_keys: list[Annotated[str, Field(max_length=255)]] = Field(
        default_factory=list, max_length=JIRA_SELECTION_LIST_MAX
    )


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


class JiraSyncResponse(GoogleDriveSyncResponse):
    """Projected Jira sync counts and per-document outcomes."""


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


def jira_sync_response(response: ConnectorSyncResponse) -> JiraSyncResponse:
    """Project Jira sync counts onto the wire schema."""
    return JiraSyncResponse(**connector_sync_response(response).model_dump())


class ChatHistoryMessage(BaseModel):
    """One prior conversation turn for grounded ask."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRuntimeRequest(BaseModel):
    """Optional client runtime overrides from Settings localStorage (#237).

    ``response_style`` is an allowlisted wording/length preset (#218). Omit or
    ``null`` for Default (no style instruction). Not stored in numeric
    ``settings``.
    """

    provider: Literal["openrouter", "ollama"] | None = None
    model: str | None = None
    ollama_base_url: str | None = None
    settings: dict[str, int | float] = Field(default_factory=dict)
    response_style: Literal["formal", "friendly", "concise"] | None = None


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
    response_style: Literal["formal", "friendly", "concise"] | None = None
    prompt_key: str | None = None
    prompt_version: str | None = None
    intent: (
        Literal[
            "tool_workflow",
            "clarification",
            "grounded_answer",
            "general_answer",
        ]
        | None
    ) = None
    routing_confidence: float | None = None
    ambiguous: bool | None = None
    path: str | None = None


FeedbackRatingLiteral = Literal["positive", "negative"]
FeedbackReasonLiteral = Literal[
    "incorrect",
    "incomplete",
    "unsupported",
    "irrelevant",
    "wrong_tool",
    "unclear",
    "unsafe",
    "other",
]


class UpsertResponseFeedbackRequest(BaseModel):
    """Body for creating or updating a response rating."""

    rating: FeedbackRatingLiteral
    reason: FeedbackReasonLiteral | None = None
    comment: str | None = Field(default=None, max_length=2000)


class ResponseFeedbackResponse(BaseModel):
    """Projected feedback record (no prompts, answers, or credentials)."""

    request_id: str
    rating: FeedbackRatingLiteral
    conversation_id: str | None = None
    client_message_id: str | None = None
    run_id: str | None = None
    reason: FeedbackReasonLiteral | None = None
    comment: str | None = None
    prompt_key: str | None = None
    prompt_version: str | None = None
    model: str | None = None
    tools: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


def response_feedback_response(feedback: object) -> ResponseFeedbackResponse:
    """Project a domain ``ResponseFeedback`` to the HTTP schema."""
    from domain.response_feedback import ResponseFeedback

    if not isinstance(feedback, ResponseFeedback):
        raise TypeError("feedback must be a ResponseFeedback")
    return ResponseFeedbackResponse(
        request_id=feedback.request_id,
        rating=feedback.rating,
        conversation_id=feedback.conversation_id,
        client_message_id=feedback.client_message_id,
        run_id=feedback.run_id,
        reason=feedback.reason,
        comment=feedback.comment,
        prompt_key=feedback.prompt_key,
        prompt_version=feedback.prompt_version,
        model=feedback.model,
        tools=list(feedback.tools),
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


class ToolCallResponse(BaseModel):
    """One projected tool invocation (authored summary, never opaque payload)."""

    tool_name: str
    ok: bool
    summary: str = ""


class SourceReferenceResponse(BaseModel):
    """Provenance id/type for projected tool results."""

    source_id: str
    source_type: str


class ToolRunResponse(BaseModel):
    """Projected Software Delivery tool-run view (no opaque payloads)."""

    summary: str
    calls: list[ToolCallResponse]
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
    test_type: str | None = None


class GeneratedTestCaseResponse(BaseModel):
    """Detailed manual or Cucumber artifact for one selected candidate."""

    candidate_id: str
    test_type: str
    automation_fit: str
    automation_rationale: str
    availability: str
    preconditions: str
    steps: list[str]
    expected_result: str
    gherkin: str
    user_edited: bool


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
    generated_cases: list[GeneratedTestCaseResponse] = []
    evidence_fingerprint: str | None = None
    skipped_edited_candidate_ids: list[str] = []
    cucumber_feature: str = ""
    cucumber_background: str = ""


class CreateTestDesignDraftRequest(BaseModel):
    """Wire body for ``POST /api/v1/test-design/drafts``."""

    conversation_id: str = Field(min_length=1)
    source_locator: SourceLocatorRequest


class PatchTestDesignDraftRequest(BaseModel):
    """Wire body for ``PATCH /api/v1/test-design/drafts/{draft_id}``."""

    expected_version: int = Field(ge=1)
    candidates: list[TestCandidateResponse] | None = None
    generated_cases: list[GeneratedTestCaseResponse] | None = None
    cucumber_feature: str | None = None
    cucumber_background: str | None = None


class TestTypeOverrideRequest(BaseModel):
    """Per-candidate type choice applied before generation."""

    candidate_id: str = Field(min_length=1)
    test_type: str = Field(min_length=1)


class GenerateTestDesignCasesRequest(BaseModel):
    """Wire body for ``POST /api/v1/test-design/drafts/{draft_id}/generate``."""

    expected_version: int = Field(ge=1)
    candidate_ids: list[str] | None = None
    type_overrides: list[TestTypeOverrideRequest] | None = None
    overwrite_edited: bool = False


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


class ExportTestDesignXrayRequest(BaseModel):
    """Wire body for ``POST /api/v1/test-design/drafts/{draft_id}/export/xray``."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    link_source_issue: bool = True


class ExportTestDesignXrayResponse(BaseModel):
    """Safe receipt: created Jira issue keys and counts only."""

    project_key: str
    created_keys: list[str]
    created_count: int
    failed_count: int
    browse_base_url: str | None


class TestDesignXrayStatusResponse(BaseModel):
    """Xray availability for a draft and the tests already created from it."""

    __test__ = False

    available: bool
    project_key: str | None
    created_keys: list[str]
    last_created_at: str | None
    browse_base_url: str | None
    link_issue_key: str | None


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
                test_type=getattr(item, "test_type", None),
            )
            for item in view.candidates  # type: ignore[attr-defined]
        ],
        coverage_gaps=[],
        version=view.version,  # type: ignore[attr-defined]
        selected_candidate_ids=list(view.selected_candidate_ids),  # type: ignore[attr-defined]
        generated_cases=[
            GeneratedTestCaseResponse(
                candidate_id=case.candidate_id,
                test_type=case.test_type,
                automation_fit=case.automation_fit,
                automation_rationale=case.automation_rationale,
                availability=case.availability,
                preconditions=case.preconditions,
                steps=list(case.steps),
                expected_result=case.expected_result,
                gherkin=case.gherkin,
                user_edited=case.user_edited,
            )
            for case in getattr(view, "generated_cases", ())
        ],
        evidence_fingerprint=getattr(view, "evidence_fingerprint", None),
        skipped_edited_candidate_ids=list(
            getattr(view, "skipped_edited_candidate_ids", ())
        ),
        cucumber_feature=getattr(view, "cucumber_feature", "") or "",
        cucumber_background=getattr(view, "cucumber_background", "") or "",
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
    style: Literal["formal", "friendly", "concise"] | None = None
    if run.response_style in ("formal", "friendly", "concise"):
        style = run.response_style
    intent: (
        Literal[
            "tool_workflow",
            "clarification",
            "grounded_answer",
            "general_answer",
        ]
        | None
    ) = None
    if run.intent in (
        "tool_workflow",
        "clarification",
        "grounded_answer",
        "general_answer",
    ):
        intent = run.intent  # type: ignore[assignment]
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
        response_style=style,
        prompt_key=run.prompt_key,
        prompt_version=None,
        intent=intent,
        routing_confidence=run.routing_confidence,
        ambiguous=run.ambiguous,
        path=run.path,
    )


def tool_run_response(view: SoftwareDeliveryRunView) -> ToolRunResponse:
    """Project a typed Software Delivery view; opaque payloads stay out."""
    return ToolRunResponse(
        summary=view.summary,
        calls=[
            ToolCallResponse(
                tool_name=call.tool_name, ok=call.ok, summary=call.summary
            )
            for call in view.calls
        ],
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
    created_at: str
    updated_at: str
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
        created_at=document.created_at.isoformat(),
        updated_at=document.updated_at.isoformat(),
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



class CreateProjectBody(BaseModel):
    """Body for creating a project; the ``project_id`` is generated."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=512)
    slug: str = Field(min_length=1, max_length=64)


class ProjectResponse(BaseModel):
    """A project in the bound workspace."""

    project_id: str
    name: str
    slug: str
    version: int


class SourceScopeBody(BaseModel):
    """Opaque connector scope; the connector owns its meaning."""

    model_config = ConfigDict(extra="forbid")

    connector_id: str = Field(min_length=1, max_length=512)
    scope_kind: str = Field(min_length=1, max_length=64)
    scope_value: str = Field(min_length=1, max_length=512)


class AssociateSourceBody(SourceScopeBody):
    """Explicitly associate a scope with a project as ``confirmed``."""

    roles: list[str] = Field(default_factory=list, max_length=32)
    acknowledged_shared_with: list[str] = Field(default_factory=list, max_length=256)


class ConfirmAssociationBody(SourceScopeBody):
    """Confirm a suggested or rejected association with compare-and-swap."""

    expected_version: int = Field(ge=1)
    roles: list[str] | None = Field(default=None, max_length=32)
    acknowledged_shared_with: list[str] = Field(default_factory=list, max_length=256)


class ProjectAssociationResponse(BaseModel):
    """One source association of a project."""

    connector_id: str
    scope_kind: str
    scope_value: str
    roles: list[str]
    state: Literal["suggested", "confirmed", "rejected"]
    evidence: list[SourceReferenceResponse]
    created_by: str
    version: int


class ProjectComponentMemberResponse(BaseModel):
    """A component member: a scope narrowed by an optional path prefix."""

    connector_id: str
    scope_kind: str
    scope_value: str
    path_prefix: str


class ProjectComponentResponse(BaseModel):
    """A project component; it has no type field."""

    component_id: str
    name: str
    reason: Literal["association_default", "operator"]
    version: int
    members: list[ProjectComponentMemberResponse]


class ProjectDetailResponse(ProjectResponse):
    """A project with its associations and components."""

    associations: list[ProjectAssociationResponse]
    components: list[ProjectComponentResponse]


def project_response(project: object) -> ProjectResponse:
    """Project a domain ``Project`` to the HTTP schema."""
    from domain.project.models import Project

    if not isinstance(project, Project):
        raise TypeError("project must be a Project")
    return ProjectResponse(
        project_id=project.project_id,
        name=project.name,
        slug=project.slug,
        version=project.version,
    )


def project_association_response(association: object) -> ProjectAssociationResponse:
    """Project a domain ``SourceAssociation`` to the HTTP schema."""
    from domain.project.models import SourceAssociation

    if not isinstance(association, SourceAssociation):
        raise TypeError("association must be a SourceAssociation")
    return ProjectAssociationResponse(
        connector_id=association.scope.connector_id,
        scope_kind=association.scope.scope_kind,
        scope_value=association.scope.scope_value,
        roles=list(association.roles),
        state=association.state.value,
        evidence=[
            SourceReferenceResponse(
                source_id=ref.source_id, source_type=str(ref.source_type)
            )
            for ref in association.evidence
        ],
        created_by=association.created_by,
        version=association.version,
    )


def project_component_response(component: object) -> ProjectComponentResponse:
    """Project a domain ``ProjectComponent`` to the HTTP schema."""
    from domain.project.models import ProjectComponent

    if not isinstance(component, ProjectComponent):
        raise TypeError("component must be a ProjectComponent")
    return ProjectComponentResponse(
        component_id=component.component_id,
        name=component.name,
        reason=component.reason,
        version=component.version,
        members=[
            ProjectComponentMemberResponse(
                connector_id=member.scope.connector_id,
                scope_kind=member.scope.scope_kind,
                scope_value=member.scope.scope_value,
                path_prefix=member.path_prefix,
            )
            for member in component.members
        ],
    )


def project_detail_response(detail: object) -> ProjectDetailResponse:
    """Project an application ``ProjectDetail`` to the HTTP schema."""
    from application.project.projects import ProjectDetail

    if not isinstance(detail, ProjectDetail):
        raise TypeError("detail must be a ProjectDetail")
    base = project_response(detail.project)
    return ProjectDetailResponse(
        **base.model_dump(),
        associations=[project_association_response(a) for a in detail.associations],
        components=[project_component_response(c) for c in detail.components],
    )
