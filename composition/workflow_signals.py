"""Composition WorkflowSignals for Test Design and Drive export (#312).

Signals separate intent recognition from readiness. They never import
LangGraph and stay out of ``application/``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import re
from typing import Protocol

from application.turn_routing import (
    TurnRoutingRequest,
    WorkflowReadiness,
    WorkflowSignal,
    WorkflowSignalResult,
)
from composition.test_design_errors import TestDesignValidationError

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

_TEST_DESIGN_TOPIC_QUESTION = re.compile(
    r"^\s*(how|who|what|why|where|when|can\s+you|could\s+you|please\s+explain|"
    r"explain)\b",
    re.IGNORECASE,
)

# Docs/prose cues for Drive bail-out. Deliberately omits issue/PR/locator
# tokens so a dual Test Design + Drive command can still conflict-clarify.
_DRIVE_DOCS_PROSE_CUES = re.compile(
    r"\b("
    r"docs?|documentation|readme|codebase|this\s+project|"
    r"in\s+this\s+repo|according\s+to|our\s+(?:docs|code|repo)|"
    r"catalog|ingested|knowledge\s+base|"
    r"how\s+(?:does|do|is|are|can)|what\s+(?:do|does|is|are)|"
    r"explain|permissions|configured|connector|pipeline|flow"
    r")\b",
    re.IGNORECASE,
)

_EXPORT_DRIVE_CLEAR = re.compile(
    r"\bexport\b.*\b(?:google\s+)?drive\b|\b(?:google\s+)?drive\b.*\bexport\b",
    re.IGNORECASE | re.DOTALL,
)

_EXPORT_PARTIAL = re.compile(
    r"(?:"
    r"^\s*export(?:\s+the\s+selected\s+tests?)?\s*$|"
    r"\b(?:send\s+(?:this|it|them)\s+to\s+drive|send\s+to\s+drive)\b"
    r")",
    re.IGNORECASE,
)

TEST_DESIGN_CLARIFY_ANSWER = (
    "I can start Test Design once you share a GitHub Issue URL or "
    "owner/repo#N reference."
)

DRIVE_PARTIAL_CLARIFY_ANSWER = (
    "Did you mean export the selected Test Design titles to Google Drive? "
    "Please say “export to Google Drive” once a draft with selected titles "
    "is ready."
)

DRIVE_MISSING_PAYLOAD_CLARIFY_ANSWER = (
    "I need a Test Design draft with selected titles before I can export to "
    "Google Drive."
)

DRIVE_UNAVAILABLE_CLARIFY_ANSWER = (
    "Google Drive export is not available right now."
)

CONFLICTING_WORKFLOWS_CLARIFY_ANSWER = (
    "I see more than one workflow in your request. Please ask for Test Design "
    "or Google Drive export separately."
)

MIXED_CUES_CLARIFY_ANSWER = (
    "Should I answer from your project sources, or give a general "
    "(non-project) brainstorm or rewrite?"
)

DEFAULT_CLARIFY_ANSWER = (
    "Could you clarify what you need? I can help with project sources, "
    "Test Design, Google Drive export, or a general (non-project) request."
)


class _DraftRepository(Protocol):
    def find_by_conversation_id(self, conversation_id: str) -> object | None: ...


DraftReadyCheck = Callable[[str | None], bool]


def _draft_has_selected_titles(draft: object | None) -> bool:
    if draft is None:
        return False
    candidates = getattr(draft, "candidates", ())
    if not isinstance(candidates, Sequence):
        return False
    for candidate in candidates:
        title = getattr(candidate, "title", None)
        selected = getattr(candidate, "selected", False)
        if (
            selected
            and isinstance(title, str)
            and title.strip()
        ):
            return True
    return False


_AFFIRMATIVE_FOLLOW_UP = re.compile(
    r"^\s*(yes|y|ok|okay|sure|please|thanks|thank\s+you)\s*[.!?]?\s*$",
    re.IGNORECASE,
)


def _prior_missing_field(
    request: TurnRoutingRequest,
    *,
    workflow_hint: str,
    field: str,
) -> bool:
    prior = request.clarification_context
    if not isinstance(prior, Mapping):
        return False
    if prior.get("workflow_hint") != workflow_hint:
        return False
    missing = prior.get("missing_fields")
    if isinstance(missing, str):
        return missing == field
    if isinstance(missing, (list, tuple)):
        return field in missing
    return False


def build_test_design_workflow_signal(
    *,
    enabled: bool = True,
) -> WorkflowSignal:
    """Return a WorkflowSignal for Test Design command + Issue readiness."""

    def _prior_awaiting_locator(request: TurnRoutingRequest) -> bool:
        return _prior_missing_field(
            request, workflow_hint="test_design", field="issue_locator"
        )

    def _incomplete_missing_locator() -> WorkflowSignalResult:
        return WorkflowSignalResult(
            workflow_hint="test_design",
            readiness=WorkflowReadiness.INCOMPLETE,
            reason="missing_fields",
            missing_fields=("issue_locator",),
            clarification_context={
                "workflow_hint": "test_design",
                "missing_fields": ("issue_locator",),
            },
        )

    def _looks_like_locator_follow_up(query: str) -> bool:
        stripped = query.strip()
        if not stripped:
            return False
        if stripped.isdigit() or _AFFIRMATIVE_FOLLOW_UP.match(stripped):
            return True
        lower = stripped.casefold()
        return "#" in stripped or "/" in stripped or "github.com" in lower

    def probe(request: TurnRoutingRequest) -> WorkflowSignalResult | None:
        if not enabled:
            return None
        query = request.query
        if not isinstance(query, str) or not query.strip():
            return None
        from_prior = _prior_awaiting_locator(request)
        # Unanchored command match (same as main's handoff). Shape guards apply
        # only when no Issue locator is present — a locator is decisive intent.
        match = _TEST_DESIGN_COMMAND.search(query)
        if match is None and not from_prior:
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
        if parsed is not None:
            return WorkflowSignalResult(
                workflow_hint="test_design",
                readiness=WorkflowReadiness.READY,
                reason="workflow_ready",
            )
        if from_prior and match is None:
            # Locator/affirmative follow-ups stay on clarification; clear pivots
            # (new questions) fall through so grounded/general can clear context.
            if _looks_like_locator_follow_up(query):
                return _incomplete_missing_locator()
            return None
        # No locator: docs/topical mentions stay on RAG; leading #304 commands
        # without an Issue still clarify.
        if query[: match.start()].strip():
            return None
        if _TEST_DESIGN_TOPIC_QUESTION.search(query) is not None:
            return None
        return _incomplete_missing_locator()

    return probe


def build_drive_export_workflow_signal(
    *,
    export_enabled: bool,
    draft_ready: DraftReadyCheck | None = None,
    drafts: _DraftRepository | None = None,
) -> WorkflowSignal:
    """Return a WorkflowSignal for Drive export intent vs payload readiness.

    Args:
        export_enabled: When False, recognized export intent yields
            ``tool_unavailable`` (never RAG).
        draft_ready: Optional readiness predicate for a conversation id.
        drafts: Optional draft repository used when ``draft_ready`` is omitted.
    """

    def _ready_for(conversation_id: str | None) -> bool:
        if draft_ready is not None:
            return draft_ready(conversation_id)
        if drafts is None or not conversation_id:
            return False
        return _draft_has_selected_titles(
            drafts.find_by_conversation_id(conversation_id)
        )

    def _tool_unavailable() -> WorkflowSignalResult:
        return WorkflowSignalResult(
            workflow_hint="drive_export",
            readiness=WorkflowReadiness.INCOMPLETE,
            reason="tool_unavailable",
            missing_fields=(),
            clarification_context={
                "workflow_hint": "drive_export",
                "missing_fields": (),
            },
        )

    def _incomplete_confirmation() -> WorkflowSignalResult:
        return WorkflowSignalResult(
            workflow_hint="drive_export",
            readiness=WorkflowReadiness.INCOMPLETE,
            reason="incomplete_workflow",
            missing_fields=("export_confirmation",),
            clarification_context={
                "workflow_hint": "drive_export",
                "missing_fields": ("export_confirmation",),
            },
        )

    def _incomplete_titles() -> WorkflowSignalResult:
        return WorkflowSignalResult(
            workflow_hint="drive_export",
            readiness=WorkflowReadiness.INCOMPLETE,
            reason="missing_fields",
            missing_fields=("selected_titles",),
            clarification_context={
                "workflow_hint": "drive_export",
                "missing_fields": ("selected_titles",),
            },
        )

    def _ready() -> WorkflowSignalResult:
        return WorkflowSignalResult(
            workflow_hint="drive_export",
            readiness=WorkflowReadiness.READY,
            reason="workflow_ready",
        )

    def probe(request: TurnRoutingRequest) -> WorkflowSignalResult | None:
        query = request.query
        if not isinstance(query, str) or not query.strip():
            return None
        clear_match = _EXPORT_DRIVE_CLEAR.search(query)
        clear = clear_match is not None
        partial_match = None if clear else _EXPORT_PARTIAL.search(query)
        partial = partial_match is not None
        awaiting_confirm = _prior_missing_field(
            request,
            workflow_hint="drive_export",
            field="export_confirmation",
        )
        awaiting_titles = _prior_missing_field(
            request,
            workflow_hint="drive_export",
            field="selected_titles",
        )
        affirmed = _AFFIRMATIVE_FOLLOW_UP.match(query.strip()) is not None
        # Structured prior + "yes" confirms the Drive export ask (never from
        # raw history alone). That supplies export_confirmation.
        confirmed_follow_up = awaiting_confirm and affirmed

        if not clear and not partial and not confirmed_follow_up:
            if awaiting_titles and affirmed:
                # Affirmation does not create selected titles — stay clarifying.
                if not export_enabled:
                    return _tool_unavailable()
                return _incomplete_titles()
            return None

        # Docs/prose questions that mention export+Drive stay on RAG (especially
        # with agent_loop off, where a signal would otherwise be tool_unavailable).
        # Issue locators are omitted from this cue set so dual-workflow commands
        # can still conflict-clarify.
        intent_match = clear_match or partial_match
        if (
            intent_match is not None
            and query[: intent_match.start()].strip()
            and _DRIVE_DOCS_PROSE_CUES.search(query) is not None
        ):
            return None
        if not export_enabled:
            return _tool_unavailable()
        if partial and not clear and not confirmed_follow_up:
            return _incomplete_confirmation()
        if not _ready_for(request.conversation_id):
            return _incomplete_titles()
        return _ready()

    return probe


def clarification_answer_for(decision_reason: str, workflow_hint: str | None) -> str:
    """Map allowlisted reason codes to fixed clarification copy."""
    if decision_reason == "conflicting_workflows":
        return CONFLICTING_WORKFLOWS_CLARIFY_ANSWER
    if decision_reason == "mixed_cues":
        return MIXED_CUES_CLARIFY_ANSWER
    if workflow_hint == "test_design":
        return TEST_DESIGN_CLARIFY_ANSWER
    if workflow_hint == "drive_export":
        if decision_reason == "tool_unavailable":
            return DRIVE_UNAVAILABLE_CLARIFY_ANSWER
        if decision_reason == "missing_fields":
            return DRIVE_MISSING_PAYLOAD_CLARIFY_ANSWER
        return DRIVE_PARTIAL_CLARIFY_ANSWER
    return DEFAULT_CLARIFY_ANSWER


__all__ = [
    "CONFLICTING_WORKFLOWS_CLARIFY_ANSWER",
    "DEFAULT_CLARIFY_ANSWER",
    "DRIVE_MISSING_PAYLOAD_CLARIFY_ANSWER",
    "DRIVE_PARTIAL_CLARIFY_ANSWER",
    "DRIVE_UNAVAILABLE_CLARIFY_ANSWER",
    "MIXED_CUES_CLARIFY_ANSWER",
    "TEST_DESIGN_CLARIFY_ANSWER",
    "build_drive_export_workflow_signal",
    "build_test_design_workflow_signal",
    "clarification_answer_for",
]
