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
_TEST_DESIGN_VALIDATION_DETAIL = "The test-design request was invalid."

OAuthPreflight = Callable[[], str]
LiveSourceReaderFactory = Callable[[str], LiveSourceReader]

_TEST_DESIGN_COMMAND = re.compile(
    r"\b("
    r"test\s*design|"
    r"design\s+tests?|"
    r"plan\s+(?:test\s+)?coverage|"
    r"coverage\s+plan|"
    r"start\s+test\s+design"
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
class GoogleDriveExportReceiptView:
    file_id: str
    file_name: str


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

    Returns None when this is not a Test Design Issue handoff (caller runs RAG),
    including topical discussion that merely mentions test design/coverage and
    phrases that match the command regex but carry no Issue reference.
    Raises TestDesignValidationError for commands with multiple distinct Issues,
    or for client source_locator mismatch.
    """
    if not software_delivery_tools_enabled(settings):
        return None
    if not isinstance(query, str) or not query.strip():
        return None
    if _TEST_DESIGN_COMMAND.search(query) is None:
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
        # Phrase match alone is not enough — no Issue means discussion, not
        # a handoff. Fall through to grounded RAG.
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
            GitHubIssueLocatorMismatchError,
            GitHubIssueNotIssueError,
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
        except (GitHubIssueNotIssueError, GitHubIssueLocatorMismatchError) as error:
            raise TestDesignValidationError(_TEST_DESIGN_VALIDATION_DETAIL) from error
        if not document.content.strip():
            raise InsufficientEvidenceError(
                "No usable grounded evidence for test coverage planning."
            )
        draft_id = str(uuid.uuid4())
        (
            SuggestTestCandidates,
            SuggestTestCandidatesRequest,
            CoverageEvidenceItem,
            budget_source_document_text,
        ) = (
            self._load_suggest_tests()
        )
        try:
            evidence = (
                CoverageEvidenceItem(
                    reference=document.reference,
                    text=budget_source_document_text(document),
                ),
            )
            chat_model = self._build_chat_model()
            repo = self._repository()
            use_case = SuggestTestCandidates(chat_model=chat_model, repository=repo)
            draft = use_case.execute(
                SuggestTestCandidatesRequest(
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
        except TestDesignValidationError:
            raise
        except Exception as error:
            from packs.software_delivery.test_design.suggest_tests import (
                TestDesignInsufficientEvidenceError,
            )
            from packs.software_delivery.test_design.errors import (
                TestDesignValidationError as PackTestDesignValidationError,
            )

            if isinstance(error, TestDesignInsufficientEvidenceError):
                raise InsufficientEvidenceError(str(error)) from error
            if isinstance(error, PackTestDesignValidationError):
                raise TestDesignValidationError(
                    _TEST_DESIGN_VALIDATION_DETAIL
                ) from error
            raise
        return _draft_view(draft)

    def get_draft(self, draft_id: str) -> TestCoverageDraftView:
        self._require_enabled()
        try:
            draft = self._repository().get(draft_id)
        except Exception as error:
            _raise_composition_validation_if_pack_error(error)
            raise
        if draft is None:
            raise TestDesignNotFoundError("draft not found")
        return _draft_view(draft)

    def patch_draft(
        self, draft_id: str, request: PatchTestDesignDraftRequest
    ) -> TestCoverageDraftView:
        self._require_enabled()
        TestCandidate, TestCoverageDraft = self._load_models()
        repo = self._repository()
        try:
            current = repo.get(draft_id)
        except Exception as error:
            _raise_composition_validation_if_pack_error(error)
            raise
        if current is None:
            raise TestDesignNotFoundError("draft not found")
        candidates = current.candidates
        if request.candidates is not None:
            try:
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
            except Exception as error:
                from packs.software_delivery.test_design.errors import (
                    TestDesignValidationError as PackTestDesignValidationError,
                )

                if isinstance(error, PackTestDesignValidationError):
                    raise TestDesignValidationError(
                        _TEST_DESIGN_VALIDATION_DETAIL
                    ) from error
                raise
        next_status = current.status
        if (
            request.candidates is not None
            and current.status == "ready"
            and not _candidates_semantically_equal(candidates, current.candidates)
        ):
            next_status = "coverage_review"
        try:
            updated = TestCoverageDraft(
                draft_id=current.draft_id,
                workspace_id=current.workspace_id,
                conversation_id=current.conversation_id,
                source_reference=current.source_reference,
                ticket_identifier=current.ticket_identifier,
                status=next_status,
                candidates=candidates,
                version=current.version,
            )
        except Exception as error:
            from packs.software_delivery.test_design.errors import (
                TestDesignValidationError as PackTestDesignValidationError,
            )

            if isinstance(error, PackTestDesignValidationError):
                raise TestDesignValidationError(
                    _TEST_DESIGN_VALIDATION_DETAIL
                ) from error
            raise
        try:
            saved = repo.update(
                updated, expected_version=request.expected_version
            )
        except VersionedStoreNotFoundError as error:
            raise TestDesignNotFoundError("draft not found") from error
        except VersionedStoreVersionConflictError as error:
            raise TestDesignVersionConflictError("version conflict") from error
        except Exception as error:
            _raise_composition_validation_if_pack_error(error)
            raise
        return _draft_view(saved)

    def confirm_draft(
        self, draft_id: str, *, expected_version: int
    ) -> TestCoverageDraftView:
        self._require_enabled()
        _TestCandidate, TestCoverageDraft = self._load_models()
        repo = self._repository()
        try:
            current = repo.get(draft_id)
        except Exception as error:
            _raise_composition_validation_if_pack_error(error)
            raise
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
            version=current.version,
        )
        try:
            saved = repo.update(updated, expected_version=expected_version)
        except VersionedStoreNotFoundError as error:
            raise TestDesignNotFoundError("draft not found") from error
        except VersionedStoreVersionConflictError as error:
            raise TestDesignVersionConflictError("version conflict") from error
        except Exception as error:
            _raise_composition_validation_if_pack_error(error)
            raise
        return _draft_view(saved)

    def export_to_google_drive(
        self,
        draft_id: str,
        *,
        folder_id: str,
        file_name: str | None = None,
        destination_label: str | None = None,
    ) -> GoogleDriveExportReceiptView:
        """Export selected titles into a user-chosen Google Drive folder."""
        import json

        from application.contracts import InvokeToolRequest
        from application.errors import ApplicationValidationError
        from composition.container import (
            build_invoke_tool,
            mark_drive_reauth,
            require_drive_export_grant,
        )
        from domain.errors import (
            ConnectorAuthError,
            ToolArgumentValidationError,
            ToolFailureError,
        )
        from infrastructure.connectors.google_drive.folder import is_drive_folder_id
        from packs.software_delivery.tools.export_test_cases_google_drive import (
            TOOL_NAME,
        )

        self._require_enabled()
        if not isinstance(folder_id, str) or not is_drive_folder_id(folder_id.strip()):
            raise TestDesignValidationError(_TEST_DESIGN_VALIDATION_DETAIL)
        folder_id = folder_id.strip()
        label = (
            destination_label.strip()
            if isinstance(destination_label, str) and destination_label.strip()
            else "Google Drive"
        )
        repo = self._repository()
        try:
            current = repo.get(draft_id)
        except Exception as error:
            _raise_composition_validation_if_pack_error(error)
            raise
        if current is None:
            raise TestDesignNotFoundError("draft not found")
        selected_titles = tuple(
            candidate.title
            for candidate in current.candidates
            if candidate.selected and candidate.title.strip()
        )
        if not selected_titles:
            raise TestDesignValidationError(
                "select at least one candidate before export"
            )
        # Persist before upload so chat agent HITL can reuse this destination
        # even when the button-path upload later fails.
        self._destination_repository().upsert(
            current.conversation_id,
            folder_id=folder_id,
            display_label=label,
        )
        tokens_store, _connection = require_drive_export_grant(self._settings)
        arguments: dict[str, object] = {
            "document_title": current.ticket_identifier,
            "titles": list(selected_titles),
            "folder_id": folder_id,
        }
        if file_name is not None:
            arguments["file_name"] = file_name
        invoke = build_invoke_tool(self._settings)
        try:
            response = invoke.execute(InvokeToolRequest(TOOL_NAME, arguments))
        except ApplicationValidationError as error:
            raise TestDesignUnavailableError(
                "Google Drive export is unavailable"
            ) from error
        except ToolArgumentValidationError as error:
            raise TestDesignValidationError(
                _TEST_DESIGN_VALIDATION_DETAIL
            ) from error
        except ConnectorAuthError as error:
            mark_drive_reauth(tokens_store, error)
        except ToolFailureError:
            raise
        try:
            payload = json.loads(response.result)
        except (TypeError, ValueError) as error:
            raise ToolFailureError("Google Drive export failed.") from error
        if not isinstance(payload, dict):
            raise ToolFailureError("Google Drive export failed.")
        file_id = payload.get("file_id")
        exported_name = payload.get("file_name")
        if not isinstance(file_id, str) or not file_id.strip():
            raise ToolFailureError("Google Drive export failed.")
        if not isinstance(exported_name, str) or not exported_name.strip():
            raise ToolFailureError("Google Drive export failed.")
        return GoogleDriveExportReceiptView(
            file_id=file_id.strip(),
            file_name=exported_name.strip(),
        )

    def set_export_destination(
        self,
        conversation_id: str,
        *,
        folder_id: str,
        destination_label: str | None = None,
    ) -> str:
        """Persist the Drive folder for later agent export / HITL prepare.

        Does not upload. Returns the stored display label.
        """
        from infrastructure.connectors.google_drive.folder import is_drive_folder_id

        self._require_enabled()
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise TestDesignValidationError(_TEST_DESIGN_VALIDATION_DETAIL)
        if not isinstance(folder_id, str) or not is_drive_folder_id(folder_id.strip()):
            raise TestDesignValidationError(_TEST_DESIGN_VALIDATION_DETAIL)
        folder_id = folder_id.strip()
        label = (
            destination_label.strip()
            if isinstance(destination_label, str) and destination_label.strip()
            else ("Home" if folder_id == "root" else "Google Drive")
        )
        self._destination_repository().upsert(
            conversation_id.strip(),
            folder_id=folder_id,
            display_label=label,
        )
        return label

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

    def _destination_repository(self):
        from composition.export_destination_store import (
            VersionedExportDestinationRepository,
        )
        from infrastructure.workspace_store.sql_store import VersionedWorkspaceStore

        return VersionedExportDestinationRepository(
            VersionedWorkspaceStore(self._store_path, self._workspace_id)
        )

    def _build_chat_model(self):
        from composition.container import build_chat_model

        return build_chat_model(self._settings)

    @staticmethod
    def _load_suggest_tests():
        from packs.software_delivery.test_design.suggest_tests import (
            CoverageEvidenceItem,
            SuggestTestCandidates,
            SuggestTestCandidatesRequest,
            budget_source_document_text,
        )

        return (
            SuggestTestCandidates,
            SuggestTestCandidatesRequest,
            CoverageEvidenceItem,
            budget_source_document_text,
        )

    @staticmethod
    def _load_models():
        from packs.software_delivery.test_design.models import (
            TestCandidate,
            TestCoverageDraft,
        )

        return TestCandidate, TestCoverageDraft


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
        version=draft.version,  # type: ignore[attr-defined]
        selected_candidate_ids=tuple(draft.selected_candidate_ids),  # type: ignore[attr-defined]
    )


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TestDesignValidationError(f"{field_name} must be non-empty")
    return value.strip()


def _raise_composition_validation_if_pack_error(error: BaseException) -> None:
    from packs.software_delivery.test_design.errors import (
        TestDesignValidationError as PackTestDesignValidationError,
    )

    if isinstance(error, PackTestDesignValidationError):
        raise TestDesignValidationError(_TEST_DESIGN_VALIDATION_DETAIL) from error


def _candidates_semantically_equal(left: object, right: object) -> bool:
    """Return True when candidate sequences match for confirmation invalidation."""
    if not isinstance(left, tuple) or not isinstance(right, tuple):
        return False
    if len(left) != len(right):
        return False
    for left_item, right_item in zip(left, right, strict=True):
        if _candidate_fingerprint(left_item) != _candidate_fingerprint(right_item):
            return False
    return True


def _candidate_fingerprint(candidate: object) -> tuple[object, ...]:
    refs = tuple(
        (ref.source_id, ref.source_type)
        for ref in getattr(candidate, "evidence_references", ())
    )
    return (
        getattr(candidate, "candidate_id", None),
        getattr(candidate, "title", None),
        getattr(candidate, "category", None),
        getattr(candidate, "rationale", None),
        getattr(candidate, "selected", None),
        getattr(candidate, "origin", None),
        refs,
    )


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
