"""Composition-facing DTOs and facade for the test-design workflow."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from application.errors import InsufficientEvidenceError
from composition.software_delivery.tools import software_delivery_tools_enabled
from composition.test_design.errors import (
    TestDesignEvidenceChangedError,
    TestDesignNotFoundError,
    TestDesignUnavailableError,
    TestDesignValidationError,
    TestDesignVersionConflictError,
)
from composition.test_design.sources import (
    AmbiguousSourceLocatorError,
    TestDesignSource,
    TestDesignSourceRegistry,
)
from domain.knowledge import SourceLocator, SourceReference
from infrastructure.config import Settings
from infrastructure.workspace_store.errors import (
    VersionedStoreNotFoundError,
    VersionedStoreVersionConflictError,
)

if TYPE_CHECKING:
    from application.contracts import AskRequest
    from packs.software_delivery.test_design.models import (
        GeneratedTestCase as PackGeneratedTestCase,
    )
    from packs.software_delivery.test_design.models import (
        TestCoverageDraft as PackTestCoverageDraft,
    )

DraftStatus = Literal["coverage_review", "ready", "case_editing"]
CandidateOrigin = Literal["suggested", "manual"]
TestCaseType = Literal["manual", "cucumber"]
AutomationFit = Literal["applicable", "not_applicable", "unclear"]
CaseAvailability = Literal["available", "insufficient_evidence"]
EvidenceOrigin = Literal["live", "client_supplied"]
CoverageCategory = Literal[
    "positive",
    "negative",
    "edge_case",
]
_TEST_DESIGN_VALIDATION_DETAIL = "The test-design request was invalid."
_NO_EVIDENCE_DETAIL = "No usable grounded evidence for test coverage planning."

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
    test_type: TestCaseType | None = None


@dataclass(frozen=True, slots=True)
class GeneratedTestCaseView:
    __test__ = False

    candidate_id: str
    test_type: TestCaseType
    automation_fit: AutomationFit
    automation_rationale: str
    availability: CaseAvailability
    preconditions: str
    steps: tuple[str, ...]
    expected_result: str
    gherkin: str
    user_edited: bool


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
    generated_cases: tuple[GeneratedTestCaseView, ...] = ()
    evidence_fingerprint: str | None = None
    skipped_edited_candidate_ids: tuple[str, ...] = ()
    cucumber_feature: str = ""
    cucumber_background: str = ""
    evidence_origin: EvidenceOrigin = "live"


@dataclass(frozen=True, slots=True)
class CreateTestDesignDraftRequest:
    conversation_id: str
    source_locator: SourceLocatorView


@dataclass(frozen=True, slots=True)
class CreateTestDesignDraftFromContentRequest:
    """Issue content an MCP client already fetched (#355); not verified live."""

    conversation_id: str
    ticket_identifier: str
    title: str
    body: str
    acceptance_criteria: str | None = None
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class PatchTestDesignDraftRequest:
    expected_version: int
    candidates: tuple[TestCandidateView, ...] | None = None
    generated_cases: tuple[GeneratedTestCaseView, ...] | None = None
    cucumber_feature: str | None = None
    cucumber_background: str | None = None


@dataclass(frozen=True, slots=True)
class GenerateTestDesignCasesRequest:
    expected_version: int
    candidate_ids: tuple[str, ...] | None = None
    type_overrides: tuple[tuple[str, TestCaseType], ...] = ()
    overwrite_edited: bool = False


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


def build_test_design_handoff_from_request(
    *,
    settings: Settings,
    request: AskRequest,
    sources: TestDesignSourceRegistry,
    source_locator: SourceLocatorView | None = None,
) -> TestDesignChatHandoffView | None:
    """Build Test Design handoff **after** a ready ``tool_workflow`` decision.

    Accepts command+locator messages and locator-only follow-ups. Raises
    TestDesignValidationError for explicit commands referencing multiple
    distinct source items, or for client source_locator mismatch. Multi-item
    discussion without a command phrase returns ``None`` (falls through).
    """
    if not software_delivery_tools_enabled(settings):
        return None
    query = request.query
    if not isinstance(query, str) or not query.strip():
        return None
    has_command = _TEST_DESIGN_COMMAND.search(query) is not None
    try:
        found = sources.extract_locator(query)
    except AmbiguousSourceLocatorError as error:
        if not has_command:
            return None
        raise TestDesignValidationError(str(error)) from error
    if found is None:
        return None
    # Locator-only follow-ups (no command phrase) are valid after clarification
    # when the router already decided tool_workflow/test_design.
    if source_locator is not None:
        _require_client_locator_match(source_locator, found, sources)
    action = resolve_start_test_design_action(
        settings=settings,
        source_locator=SourceLocatorView(
            provider=found.provider, locator=found.locator
        ),
    )
    if action is None:
        return None
    return TestDesignChatHandoffView(
        answer=TEST_DESIGN_HANDOFF_ANSWER,
        action=action,
    )


def try_test_design_chat_handoff(
    *,
    settings: Settings,
    query: str,
    sources: TestDesignSourceRegistry,
    source_locator: SourceLocatorView | None = None,
) -> TestDesignChatHandoffView | None:
    """Deprecated pre-router helper; prefer post-decision handoff builder.

    Kept for unit tests that call the helper directly. Incomplete commands
    (no Issue) return ``None`` — routing clarification is owned by
    :class:`~application.turn_routing.TurnRouter`.
    """
    from application.contracts import AskRequest

    return build_test_design_handoff_from_request(
        settings=settings,
        request=AskRequest(query=query),
        sources=sources,
        source_locator=source_locator,
    )


class TestDesignFacade:
    """HTTP-facing facade: pack gate, live source fetch, store bridge."""

    __test__ = False

    def __init__(
        self,
        *,
        settings: Settings,
        store_path: Path,
        workspace_id: str,
        sources: TestDesignSourceRegistry,
    ) -> None:
        self._settings = settings
        self._store_path = store_path
        self._workspace_id = workspace_id
        self._sources = sources
        self._repo = None

    def resolve_source_locator(self, locator: str) -> SourceLocatorView:
        """Pick the one registered source whose ``canonicalize`` accepts *locator*."""
        self._require_enabled()
        resolved = self._sources.resolve_locator(locator)
        return SourceLocatorView(provider=resolved.provider, locator=resolved.locator)

    def create_draft(
        self, request: CreateTestDesignDraftRequest
    ) -> TestCoverageDraftView:
        self._require_enabled()
        source, locator = self._resolve_locator(request.source_locator)
        self._require_workspace()
        document = source.reader().fetch(
            SourceLocator(provider=source.provider, locator=locator)
        )
        if not document.content.strip():
            raise InsufficientEvidenceError(_NO_EVIDENCE_DETAIL)
        _, _, _, budget_source_document_text = self._load_suggest_tests()
        return self._suggest_draft(
            conversation_id=request.conversation_id,
            reference=document.reference,
            ticket_identifier=locator,
            source_provider=source.provider,
            budgeted=lambda: budget_source_document_text(document),
            evidence_origin="live",
        )

    def create_draft_from_content(
        self, request: CreateTestDesignDraftFromContentRequest
    ) -> TestCoverageDraftView:
        """Create a draft from client-supplied Issue content (#355).

        The content is rendered once and persisted with the draft; content
        that does not fit the evidence budget is rejected, never truncated.
        No live source is consulted now or on confirm/generate.
        """
        from packs.software_delivery.test_design.client_evidence import (
            CLIENT_SOURCE_PROVIDER,
            client_source_reference,
            render_client_evidence,
        )

        self._require_enabled()
        if not isinstance(request, CreateTestDesignDraftFromContentRequest):
            raise TestDesignValidationError(_TEST_DESIGN_VALIDATION_DETAIL)
        self._require_workspace()
        try:
            rendered = render_client_evidence(
                ticket_identifier=request.ticket_identifier,
                title=request.title,
                body=request.body,
                acceptance_criteria=request.acceptance_criteria,
                source_url=request.source_url,
            )
            reference = client_source_reference(request.ticket_identifier)
        except Exception as error:
            _raise_composition_validation_if_pack_error(error)
            raise
        return self._suggest_draft(
            conversation_id=request.conversation_id,
            reference=reference,
            ticket_identifier=request.ticket_identifier.strip(),
            source_provider=CLIENT_SOURCE_PROVIDER,
            budgeted=lambda: rendered,
            evidence_origin="client_supplied",
        )

    def _suggest_draft(
        self,
        *,
        conversation_id: str,
        reference: SourceReference,
        ticket_identifier: str,
        source_provider: str,
        budgeted: Callable[[], str],
        evidence_origin: EvidenceOrigin,
    ) -> TestCoverageDraftView:
        draft_id = str(uuid.uuid4())
        (
            SuggestTestCandidates,
            SuggestTestCandidatesRequest,
            CoverageEvidenceItem,
            _budget,
        ) = (
            self._load_suggest_tests()
        )
        try:
            evidence = (
                CoverageEvidenceItem(reference=reference, text=budgeted()),
            )
            chat_model = self._build_chat_model()
            repo = self._repository()
            use_case = SuggestTestCandidates(chat_model=chat_model, repository=repo)
            draft = use_case.execute(
                SuggestTestCandidatesRequest(
                    draft_id=draft_id,
                    workspace_id=self._workspace_id,
                    conversation_id=_require_text(conversation_id, "conversation_id"),
                    source_reference=SourceReference(
                        reference.source_id,
                        reference.source_type,
                    ),
                    ticket_identifier=ticket_identifier,
                    source_provider=source_provider,
                    evidence=evidence,
                    evidence_origin=evidence_origin,
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
        (
            GeneratedTestCase,
            coverage_candidates_equal,
            drop_generated_cases,
            is_deselection_only,
            keep_unchanged_cases,
            is_title_only_change,
        ) = self._load_case_helpers()
        repo = self._repository()
        try:
            current = repo.get(draft_id)
        except Exception as error:
            _raise_composition_validation_if_pack_error(error)
            raise
        if current is None:
            raise TestDesignNotFoundError("draft not found")

        candidates = current.candidates
        generated_cases = current.generated_cases
        next_status = current.status
        next_fingerprint = current.evidence_fingerprint
        next_cucumber_feature = current.cucumber_feature
        next_cucumber_background = current.cucumber_background

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
                        test_type=item.test_type,
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
            still_selected = {
                candidate.candidate_id for candidate in candidates if candidate.selected
            }
            if current.status in {"ready", "case_editing"} and is_title_only_change(
                current.candidates, candidates
            ):
                pass
            elif (
                current.status in {"ready", "case_editing"}
                and still_selected
                and is_deselection_only(current.candidates, candidates)
            ):
                generated_cases = tuple(
                    case
                    for case in drop_generated_cases(
                        current.generated_cases,
                        previous=current.candidates,
                        updated=candidates,
                    )
                    if case.candidate_id in still_selected
                )
            elif not coverage_candidates_equal(candidates, current.candidates):
                next_status = "coverage_review"
                generated_cases = keep_unchanged_cases(
                    current.generated_cases,
                    previous=current.candidates,
                    updated=candidates,
                )
                next_fingerprint = None
            else:
                generated_cases = drop_generated_cases(
                    current.generated_cases,
                    previous=current.candidates,
                    updated=candidates,
                )

        if request.generated_cases is not None:
            if next_status not in {"ready", "case_editing"}:
                raise TestDesignValidationError(_TEST_DESIGN_VALIDATION_DETAIL)
            existing_ids = {case.candidate_id for case in generated_cases}
            try:
                patched_cases: list[PackGeneratedTestCase] = []
                incoming_by_id = {
                    item.candidate_id: item for item in request.generated_cases
                }
                for case in generated_cases:
                    incoming = incoming_by_id.get(case.candidate_id)
                    if incoming is None:
                        patched_cases.append(case)
                        continue
                    patched_cases.append(
                        GeneratedTestCase(
                            candidate_id=incoming.candidate_id,
                            test_type=incoming.test_type,
                            automation_fit=incoming.automation_fit,
                            automation_rationale=incoming.automation_rationale,
                            availability=incoming.availability,
                            preconditions=incoming.preconditions,
                            steps=tuple(incoming.steps),
                            expected_result=incoming.expected_result,
                            gherkin=incoming.gherkin,
                            user_edited=True,
                        )
                    )
                unknown = set(incoming_by_id) - existing_ids
                if unknown:
                    raise TestDesignValidationError(_TEST_DESIGN_VALIDATION_DETAIL)
                generated_cases = tuple(patched_cases)
                next_status = "case_editing"
            except TestDesignValidationError:
                raise
            except Exception as error:
                from packs.software_delivery.test_design.errors import (
                    TestDesignValidationError as PackTestDesignValidationError,
                )

                if isinstance(error, PackTestDesignValidationError):
                    raise TestDesignValidationError(
                        _TEST_DESIGN_VALIDATION_DETAIL
                    ) from error
                raise

        if request.cucumber_feature is not None:
            next_cucumber_feature = request.cucumber_feature
        if request.cucumber_background is not None:
            next_cucumber_background = request.cucumber_background

        try:
            updated = TestCoverageDraft(
                draft_id=current.draft_id,
                workspace_id=current.workspace_id,
                conversation_id=current.conversation_id,
                source_reference=current.source_reference,
                ticket_identifier=current.ticket_identifier,
                source_provider=current.source_provider,
                status=next_status,
                candidates=candidates,
                version=current.version,
                generated_cases=generated_cases,
                evidence_fingerprint=next_fingerprint,
                cucumber_feature=next_cucumber_feature,
                cucumber_background=next_cucumber_background,
                evidence_origin=current.evidence_origin,
                client_evidence_text=current.client_evidence_text,
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
        if current.version != expected_version:
            raise TestDesignVersionConflictError("version conflict")
        if current.status in {"ready", "case_editing"}:
            return _draft_view(current)
        if not any(c.selected for c in current.candidates):
            raise TestDesignValidationError(
                "select at least one candidate before confirm"
            )
        _reference, _budgeted, fingerprint = self._evidence_for(current)
        selected_ids = {c.candidate_id for c in current.candidates if c.selected}
        kept_cases = tuple(
            case
            for case in current.generated_cases
            if case.candidate_id in selected_ids
        )
        updated = TestCoverageDraft(
            draft_id=current.draft_id,
            workspace_id=current.workspace_id,
            conversation_id=current.conversation_id,
            source_reference=current.source_reference,
            ticket_identifier=current.ticket_identifier,
            source_provider=current.source_provider,
            status="case_editing" if kept_cases else "ready",
            candidates=current.candidates,
            version=current.version,
            generated_cases=kept_cases,
            evidence_fingerprint=fingerprint,
            cucumber_feature=current.cucumber_feature if kept_cases else "",
            cucumber_background=current.cucumber_background if kept_cases else "",
            evidence_origin=current.evidence_origin,
            client_evidence_text=current.client_evidence_text,
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

    def generate_cases(
        self, draft_id: str, request: GenerateTestDesignCasesRequest
    ) -> TestCoverageDraftView:
        self._require_enabled()
        repo = self._repository()
        try:
            current = repo.get(draft_id)
        except Exception as error:
            _raise_composition_validation_if_pack_error(error)
            raise
        if current is None:
            raise TestDesignNotFoundError("draft not found")
        if current.status not in {"ready", "case_editing"}:
            raise TestDesignValidationError(_TEST_DESIGN_VALIDATION_DETAIL)

        (
            GenerateTestCases,
            GenerateTestCasesRequest,
            TypeOverride,
            CoverageEvidenceItem,
        ) = self._load_generate_cases()
        try:
            type_overrides = tuple(
                TypeOverride(candidate_id=candidate_id, test_type=test_type)
                for candidate_id, test_type in request.type_overrides
            )
        except Exception as error:
            _raise_composition_validation_if_pack_error(error)
            raise

        reference, budgeted, fingerprint = self._evidence_for(current)
        if (
            current.evidence_fingerprint is not None
            and current.evidence_fingerprint != fingerprint
        ):
            raise TestDesignEvidenceChangedError("evidence changed")

        try:
            outcome = GenerateTestCases(
                chat_model=self._build_chat_model(),
                repository=repo,
            ).execute(
                GenerateTestCasesRequest(
                    draft_id=draft_id,
                    expected_version=request.expected_version,
                    evidence=(
                        CoverageEvidenceItem(
                            reference=reference,
                            text=budgeted,
                        ),
                    ),
                    evidence_fingerprint=fingerprint,
                    candidate_ids=request.candidate_ids,
                    type_overrides=type_overrides,
                    overwrite_edited=request.overwrite_edited,
                )
            )
        except VersionedStoreVersionConflictError as error:
            raise TestDesignVersionConflictError("version conflict") from error
        except VersionedStoreNotFoundError as error:
            raise TestDesignNotFoundError("draft not found") from error
        except Exception as error:
            from packs.software_delivery.test_design.errors import (
                TestDesignValidationError as PackTestDesignValidationError,
            )

            if isinstance(error, PackTestDesignValidationError):
                raise TestDesignValidationError(
                    _TEST_DESIGN_VALIDATION_DETAIL
                ) from error
            _raise_composition_validation_if_pack_error(error)
            raise
        return _draft_view(
            outcome.draft,
            skipped_edited_candidate_ids=outcome.skipped_edited_candidate_ids,
        )

    def _resolve_locator(
        self, value: SourceLocatorView
    ) -> tuple[TestDesignSource, str]:
        if not isinstance(value, SourceLocatorView):
            raise TestDesignValidationError("source_locator is required")
        source = self._sources.resolve(value.provider)
        return source, source.canonicalize(value.locator)

    def _evidence_for(
        self, draft: PackTestCoverageDraft
    ) -> tuple[SourceReference, str, str]:
        """Return the draft's evidence reference, budgeted text and fingerprint.

        Client-supplied drafts use their stored evidence; live drafts re-fetch
        from their own source.

        Raises:
            TestDesignEvidenceChangedError: The live source now resolves to a
                different item.
        """
        from packs.software_delivery.test_design.client_evidence import (
            evidence_fingerprint,
        )

        self._require_workspace()
        if draft.evidence_origin == "client_supplied":
            reference = draft.source_reference
            budgeted = draft.client_evidence_text
            return reference, budgeted, evidence_fingerprint(reference, budgeted)
        source = self._sources.resolve(draft.source_provider)
        document = source.reader().fetch(
            SourceLocator(provider=source.provider, locator=draft.ticket_identifier)
        )
        if not document.content.strip():
            raise InsufficientEvidenceError(_NO_EVIDENCE_DETAIL)
        if (
            document.reference.source_id != draft.source_reference.source_id
            or document.reference.source_type != draft.source_reference.source_type
        ):
            raise TestDesignEvidenceChangedError("evidence changed")
        _, _, _, budget_source_document_text = self._load_suggest_tests()
        budgeted = budget_source_document_text(document)
        return (
            document.reference,
            budgeted,
            evidence_fingerprint(document.reference, budgeted),
        )

    def export_to_google_drive(
        self,
        draft_id: str,
        *,
        folder_id: str,
        file_name: str | None = None,
        destination_label: str | None = None,
    ) -> GoogleDriveExportReceiptView:
        """Export selected tests and their cases into a Google Drive folder."""
        import json

        from application.contracts import InvokeToolRequest
        from application.errors import ApplicationValidationError
        from composition.container import build_invoke_tool
        from composition.google_drive.connection import (
            mark_drive_reauth,
            require_drive_export_grant,
        )
        from composition.software_delivery.export import (
            draft_export_case_arguments,
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
            **draft_export_case_arguments(current),
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
            from composition.test_design.store import (
                VersionedTestCoverageDraftRepository,
            )
            from infrastructure.workspace_store.sql_store import (
                VersionedWorkspaceStore,
            )

            store = VersionedWorkspaceStore(self._store_path, self._workspace_id)
            self._repo = VersionedTestCoverageDraftRepository(store)
        return self._repo

    def _destination_repository(self):
        from composition.drive_export.destination_store import (
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

    @staticmethod
    def _load_case_helpers():
        from packs.software_delivery.test_design.models import (
            GeneratedTestCase,
            coverage_candidates_equal,
            drop_generated_cases_for_type_changes,
            is_deselection_only,
            is_title_only_change,
            keep_generated_cases_for_unchanged_candidates,
        )

        return (
            GeneratedTestCase,
            coverage_candidates_equal,
            drop_generated_cases_for_type_changes,
            is_deselection_only,
            keep_generated_cases_for_unchanged_candidates,
            is_title_only_change,
        )

    @staticmethod
    def _load_generate_cases():
        from packs.software_delivery.test_design.generate_cases import (
            GenerateTestCases,
            GenerateTestCasesRequest,
            TypeOverride,
        )
        from packs.software_delivery.test_design.suggest_tests import (
            CoverageEvidenceItem,
        )

        return (
            GenerateTestCases,
            GenerateTestCasesRequest,
            TypeOverride,
            CoverageEvidenceItem,
        )


def _draft_view(
    draft: object,
    *,
    skipped_edited_candidate_ids: tuple[str, ...] = (),
) -> TestCoverageDraftView:
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
                test_type=getattr(item, "test_type", None),
            )
            for item in draft.candidates  # type: ignore[attr-defined]
        ),
        version=draft.version,  # type: ignore[attr-defined]
        selected_candidate_ids=tuple(draft.selected_candidate_ids),  # type: ignore[attr-defined]
        generated_cases=tuple(
            GeneratedTestCaseView(
                candidate_id=case.candidate_id,
                test_type=case.test_type,
                automation_fit=case.automation_fit,
                automation_rationale=case.automation_rationale,
                availability=case.availability,
                preconditions=case.preconditions,
                steps=tuple(case.steps),
                expected_result=case.expected_result,
                gherkin=case.gherkin,
                user_edited=case.user_edited,
            )
            for case in getattr(draft, "generated_cases", ())
        ),
        evidence_fingerprint=getattr(draft, "evidence_fingerprint", None),
        skipped_edited_candidate_ids=skipped_edited_candidate_ids,
        cucumber_feature=getattr(draft, "cucumber_feature", "") or "",
        cucumber_background=getattr(draft, "cucumber_background", "") or "",
        evidence_origin=getattr(draft, "evidence_origin", "live"),
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


def _require_client_locator_match(
    value: SourceLocatorView,
    found: SourceLocator,
    sources: TestDesignSourceRegistry,
) -> None:
    mismatch = "source_locator must match the source referenced in the query"
    if not isinstance(value, SourceLocatorView):
        raise TestDesignValidationError("source_locator is required")
    provider = _require_text(value.provider, "provider")
    if provider.casefold() != found.provider.casefold():
        raise TestDesignValidationError(mismatch)
    client_locator = sources.resolve(found.provider).canonicalize(value.locator)
    if client_locator.casefold() != found.locator.casefold():
        raise TestDesignValidationError(mismatch)


__all__ = [
    "ChatWorkflowActionView",
    "CreateTestDesignDraftFromContentRequest",
    "CreateTestDesignDraftRequest",
    "GenerateTestDesignCasesRequest",
    "GeneratedTestCaseView",
    "PatchTestDesignDraftRequest",
    "SourceLocatorView",
    "SourceReferenceView",
    "TEST_DESIGN_HANDOFF_ANSWER",
    "TestCandidateView",
    "TestCoverageDraftView",
    "TestDesignChatHandoffView",
    "TestDesignFacade",
    "resolve_start_test_design_action",
    "build_test_design_handoff_from_request",
    "try_test_design_chat_handoff",
]
