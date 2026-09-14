"""Composition-facing DTOs and facade for the test-design workflow."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from application.errors import (
    GitHubNotConnectedError,
    GitHubReauthorizationRequiredError,
    InsufficientEvidenceError,
)
from composition.software_delivery_tools import software_delivery_tools_enabled
from composition.test_design_errors import (
    TestDesignNotFoundError,
    TestDesignUnavailableError,
    TestDesignValidationError,
    TestDesignVersionConflictError,
)
from domain.knowledge import SourceLocator, SourceReference
from domain.ports import LiveSourceReader
from infrastructure.config import Settings
from infrastructure.workspace_store.errors import (
    VersionedStoreNotFoundError,
    VersionedStoreVersionConflictError,
)

DraftStatus = Literal["coverage_review", "ready"]
CandidateOrigin = Literal["suggested", "manual"]
CoverageCategory = Literal[
    "positive",
    "negative",
    "edge_case",
]

OAuthPreflight = Callable[[], str]
LiveSourceReaderFactory = Callable[[str], LiveSourceReader]

_TEST_DESIGN_INTENT = re.compile(
    r"\b("
    r"test\s*design|"
    r"design\s+tests?|"
    r"plan\s+(?:test\s+)?coverage|"
    r"coverage\s+plan|"
    r"test\s+coverage"
    r")\b",
    re.IGNORECASE,
)

TEST_DESIGN_HANDOFF_ANSWER = (
    "I can start Test Design from that GitHub Issue. "
    "Use Start Test Design to fetch the issue live and plan coverage."
)


@dataclass(frozen=True, slots=True)
class SourceLocatorView:
    provider: str
    locator: str


@dataclass(frozen=True, slots=True)
class SourceReferenceView:
    source_id: str
    source_type: str


@dataclass(frozen=True, slots=True)
class CoverageGapView:
    category: CoverageCategory
    detail: str


@dataclass(frozen=True, slots=True)
class TestCandidateView:
    __test__ = False

    candidate_id: str
    title: str
    category: CoverageCategory
    rationale: str
    evidence_references: tuple[SourceReferenceView, ...]
    selected: bool
    origin: CandidateOrigin


@dataclass(frozen=True, slots=True)
class TestCoverageDraftView:
    __test__ = False

    draft_id: str
    workspace_id: str
    conversation_id: str
    source_reference: SourceReferenceView
    ticket_identifier: str
    status: DraftStatus
    candidates: tuple[TestCandidateView, ...]
    coverage_gaps: tuple[CoverageGapView, ...]
    version: int
    selected_candidate_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CreateTestDesignDraftRequest:
    conversation_id: str
    source_locator: SourceLocatorView


@dataclass(frozen=True, slots=True)
class PatchTestDesignDraftRequest:
    expected_version: int
    candidates: tuple[TestCandidateView, ...] | None = None


@dataclass(frozen=True, slots=True)
class ChatWorkflowActionView:
    """Pack-agnostic chat handoff action for the wire."""

    kind: Literal["start_workflow", "open_workflow"]
    workflow_id: str
    label: str
    source_locator: SourceLocatorView | None = None
    draft_id: str | None = None


@dataclass(frozen=True, slots=True)
class TestDesignChatHandoffView:
    """Fixed server-authored ask response that bypasses RAG."""

    answer: str
    action: ChatWorkflowActionView


def resolve_start_test_design_action(
    *,
    settings: Settings,
    source_locator: SourceLocatorView | None,
) -> ChatWorkflowActionView | None:
    """Return a Start Test Design action when pack is on and locator is valid."""
    if not software_delivery_tools_enabled(settings):
        return None
    if source_locator is None:
        return None
    provider = source_locator.provider.strip()
    locator = source_locator.locator.strip()
    if not provider or not locator:
        return None
    return ChatWorkflowActionView(
        kind="start_workflow",
        workflow_id="software-delivery.test-design",
        label="Start Test Design",
        source_locator=SourceLocatorView(provider=provider, locator=locator),
    )


def try_test_design_chat_handoff(
    *,
    settings: Settings,
    query: str,
    source_locator: SourceLocatorView | None = None,
) -> TestDesignChatHandoffView | None:
    """Detect Test Design handoff before ask.execute; return fixed answer + action.

    Returns None when this is not a Test Design Issue handoff (caller runs RAG).
    Raises TestDesignValidationError on ambiguous refs or locator mismatch.
    """
    if not software_delivery_tools_enabled(settings):
        return None
    if not isinstance(query, str) or not query.strip():
        return None
    if _TEST_DESIGN_INTENT.search(query) is None:
        return None
    from infrastructure.connectors.github.issue_locator import (
        AmbiguousGitHubIssueLocatorError,
        extract_github_issue_locator,
    )

    try:
        parsed = extract_github_issue_locator(query)
    except AmbiguousGitHubIssueLocatorError as error:
        raise TestDesignValidationError(
            "Query must reference exactly one GitHub Issue"
        ) from error
    if parsed is None:
        return None
    canonical = parsed.canonical
    if source_locator is not None:
        client_locator = _require_github_locator_view(source_locator)
        if client_locator.locator.casefold() != canonical.casefold():
            raise TestDesignValidationError(
                "source_locator must match the GitHub Issue in the query"
            )
    action = resolve_start_test_design_action(
        settings=settings,
        source_locator=SourceLocatorView(provider="github", locator=canonical),
    )
    if action is None:
        return None
    return TestDesignChatHandoffView(
        answer=TEST_DESIGN_HANDOFF_ANSWER,
        action=action,
    )


class TestDesignFacade:
    """HTTP-facing facade: pack gate, live Issue fetch, store bridge."""

    __test__ = False

    def __init__(
        self,
        *,
        settings: Settings,
        store_path: Path,
        workspace_id: str,
        oauth_preflight: OAuthPreflight,
        live_source_reader_factory: LiveSourceReaderFactory,
    ) -> None:
        self._settings = settings
        self._store_path = store_path
        self._workspace_id = workspace_id
        self._oauth_preflight = oauth_preflight
        self._live_source_reader_factory = live_source_reader_factory
        self._repo = None

    def create_draft(
        self, request: CreateTestDesignDraftRequest
    ) -> TestCoverageDraftView:
        self._require_enabled()
        locator_view = _require_github_locator_view(request.source_locator)
        self._require_workspace()
        access_token = self._oauth_preflight()
        if not isinstance(access_token, str) or not access_token.strip():
            raise GitHubNotConnectedError("GitHub is not connected")
        reader = self._live_source_reader_factory(access_token.strip())
        from infrastructure.connectors.github.issue_source_reader import (
            GitHubIssueEmptyBodyError,
        )

        try:
            document = reader.fetch(
                SourceLocator(
                    provider=locator_view.provider,
                    locator=locator_view.locator,
                )
            )
        except GitHubIssueEmptyBodyError as error:
            raise InsufficientEvidenceError(
                "No usable grounded evidence for test coverage planning."
            ) from error
        except Exception as error:
            message = str(error)
            if "Pull Request" in message or "did not match" in message:
                raise TestDesignValidationError(message) from error
            raise
        if not document.content.strip():
            raise InsufficientEvidenceError(
                "No usable grounded evidence for test coverage planning."
            )
        draft_id = str(uuid.uuid4())
        PlanCoverage, PlanCoverageRequest, CoverageEvidenceItem = (
            self._load_plan_coverage()
        )
        evidence = (
            CoverageEvidenceItem(
                reference=document.reference,
                text=document.content,
            ),
        )
        chat_model = self._build_chat_model()
        repo = self._repository()
        use_case = PlanCoverage(chat_model=chat_model, repository=repo)
        try:
            draft = use_case.execute(
                PlanCoverageRequest(
                    draft_id=draft_id,
                    workspace_id=self._workspace_id,
                    conversation_id=_require_text(
                        request.conversation_id, "conversation_id"
                    ),
                    source_reference=SourceReference(
                        document.reference.source_id,
                        document.reference.source_type,
                    ),
                    ticket_identifier=locator_view.locator,
                    evidence=evidence,
                )
            )
        except Exception as error:
            from packs.software_delivery.test_design.plan_coverage import (
                TestDesignInsufficientEvidenceError,
            )

            if isinstance(error, TestDesignInsufficientEvidenceError):
                raise InsufficientEvidenceError(str(error)) from error
            raise
        return _draft_view(draft)

    def get_draft(self, draft_id: str) -> TestCoverageDraftView:
        self._require_enabled()
        draft = self._repository().get(draft_id)
        if draft is None:
            raise TestDesignNotFoundError("draft not found")
        return _draft_view(draft)

    def patch_draft(
        self, draft_id: str, request: PatchTestDesignDraftRequest
    ) -> TestCoverageDraftView:
        self._require_enabled()
        TestCandidate, TestCoverageDraft, _CoverageGap = self._load_models()
        repo = self._repository()
        current = repo.get(draft_id)
        if current is None:
            raise TestDesignNotFoundError("draft not found")
        candidates = current.candidates
        if request.candidates is not None:
            candidates = tuple(
                TestCandidate(
                    candidate_id=item.candidate_id,
                    title=item.title,
                    category=item.category,
                    rationale=item.rationale,
                    evidence_references=tuple(
                        SourceReference(ref.source_id, ref.source_type)
                        for ref in item.evidence_references
                    ),
                    selected=item.selected,
                    origin=item.origin,
                )
                for item in request.candidates
            )
        updated = TestCoverageDraft(
            draft_id=current.draft_id,
            workspace_id=current.workspace_id,
            conversation_id=current.conversation_id,
            source_reference=current.source_reference,
            ticket_identifier=current.ticket_identifier,
            status=current.status,
            candidates=candidates,
            coverage_gaps=current.coverage_gaps,
            version=current.version,
        )
        try:
            saved = repo.update(
                updated, expected_version=request.expected_version
            )
        except VersionedStoreNotFoundError as error:
            raise TestDesignNotFoundError("draft not found") from error
        except VersionedStoreVersionConflictError as error:
            raise TestDesignVersionConflictError("version conflict") from error
        return _draft_view(saved)

    def confirm_draft(
        self, draft_id: str, *, expected_version: int
    ) -> TestCoverageDraftView:
        self._require_enabled()
        _TestCandidate, TestCoverageDraft, _CoverageGap = self._load_models()
        repo = self._repository()
        current = repo.get(draft_id)
        if current is None:
            raise TestDesignNotFoundError("draft not found")
        if current.status == "ready" and current.version == expected_version:
            return _draft_view(current)
        if not any(c.selected for c in current.candidates):
            raise TestDesignValidationError(
                "select at least one candidate before confirm"
            )
        updated = TestCoverageDraft(
            draft_id=current.draft_id,
            workspace_id=current.workspace_id,
            conversation_id=current.conversation_id,
            source_reference=current.source_reference,
            ticket_identifier=current.ticket_identifier,
            status="ready",
            candidates=current.candidates,
            coverage_gaps=current.coverage_gaps,
            version=current.version,
        )
        try:
            saved = repo.update(updated, expected_version=expected_version)
        except VersionedStoreNotFoundError as error:
            raise TestDesignNotFoundError("draft not found") from error
        except VersionedStoreVersionConflictError as error:
            raise TestDesignVersionConflictError("version conflict") from error
        return _draft_view(saved)

    def _require_enabled(self) -> None:
        if not software_delivery_tools_enabled(self._settings):
            raise TestDesignUnavailableError("test design unavailable")

    def _require_workspace(self) -> None:
        if not isinstance(self._workspace_id, str) or not self._workspace_id.strip():
            raise TestDesignValidationError("workspace_id is required")

    def _repository(self):
        if self._repo is None:
            from composition.test_design_store import (
                VersionedTestCoverageDraftRepository,
            )
            from infrastructure.workspace_store.sql_store import (
                VersionedWorkspaceStore,
            )

            store = VersionedWorkspaceStore(self._store_path, self._workspace_id)
            self._repo = VersionedTestCoverageDraftRepository(store)
        return self._repo

    def _build_chat_model(self):
        from composition.container import build_chat_model

        return build_chat_model(self._settings)

    @staticmethod
    def _load_plan_coverage():
        from packs.software_delivery.test_design.plan_coverage import (
            CoverageEvidenceItem,
            PlanCoverage,
            PlanCoverageRequest,
        )

        return PlanCoverage, PlanCoverageRequest, CoverageEvidenceItem

    @staticmethod
    def _load_models():
        from packs.software_delivery.test_design.models import (
            CoverageGap,
            TestCandidate,
            TestCoverageDraft,
        )

        return TestCandidate, TestCoverageDraft, CoverageGap


def _draft_view(draft: object) -> TestCoverageDraftView:
    return TestCoverageDraftView(
        draft_id=draft.draft_id,  # type: ignore[attr-defined]
        workspace_id=draft.workspace_id,  # type: ignore[attr-defined]
        conversation_id=draft.conversation_id,  # type: ignore[attr-defined]
        source_reference=SourceReferenceView(
            source_id=draft.source_reference.source_id,  # type: ignore[attr-defined]
            source_type=draft.source_reference.source_type,  # type: ignore[attr-defined]
        ),
        ticket_identifier=draft.ticket_identifier,  # type: ignore[attr-defined]
        status=draft.status,  # type: ignore[attr-defined]
        candidates=tuple(
            TestCandidateView(
                candidate_id=item.candidate_id,
                title=item.title,
                category=item.category,
                rationale=item.rationale,
                evidence_references=tuple(
                    SourceReferenceView(ref.source_id, ref.source_type)
                    for ref in item.evidence_references
                ),
                selected=item.selected,
                origin=item.origin,
            )
            for item in draft.candidates  # type: ignore[attr-defined]
        ),
        coverage_gaps=tuple(
            CoverageGapView(category=gap.category, detail=gap.detail)
            for gap in draft.coverage_gaps  # type: ignore[attr-defined]
        ),
        version=draft.version,  # type: ignore[attr-defined]
        selected_candidate_ids=tuple(draft.selected_candidate_ids),  # type: ignore[attr-defined]
    )


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TestDesignValidationError(f"{field_name} must be non-empty")
    return value.strip()


def _require_github_locator_view(value: SourceLocatorView) -> SourceLocatorView:
    if not isinstance(value, SourceLocatorView):
        raise TestDesignValidationError("source_locator is required")
    provider = _require_text(value.provider, "provider")
    if provider.casefold() != "github":
        raise TestDesignValidationError("source_locator.provider must be github")
    from infrastructure.connectors.github.issue_locator import (
        InvalidGitHubIssueLocatorError,
        canonicalize_github_issue_locator,
    )

    try:
        locator = canonicalize_github_issue_locator(value.locator)
    except InvalidGitHubIssueLocatorError as error:
        raise TestDesignValidationError(
            "source_locator.locator must be a GitHub Issue URL or owner/repo#number"
        ) from error
    return SourceLocatorView(provider="github", locator=locator)


# Re-export for callers that still type-check connection errors on create.
__all__ = [
    "ChatWorkflowActionView",
    "CreateTestDesignDraftRequest",
    "CoverageGapView",
    "GitHubNotConnectedError",
    "GitHubReauthorizationRequiredError",
    "PatchTestDesignDraftRequest",
    "SourceLocatorView",
    "SourceReferenceView",
    "TEST_DESIGN_HANDOFF_ANSWER",
    "TestCandidateView",
    "TestCoverageDraftView",
    "TestDesignChatHandoffView",
    "TestDesignFacade",
    "resolve_start_test_design_action",
    "try_test_design_chat_handoff",
]
