"""Pack-neutral conversational turn routing (pre-retrieval).

``TurnRouter`` is the single routing decision boundary. Pack-specific workflows
are injected as :class:`WorkflowSignal` callables; this module never imports
packs or LangGraph.

``routing_confidence`` values are **fixed heuristic scores**, not calibrated
probabilities.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Literal

from application.errors import ApplicationValidationError
from domain.models import Message

# Fixed heuristic scores (not calibrated probability).
CONFIDENCE_READY = 0.9
CONFIDENCE_INCOMPLETE = 0.8
CONFIDENCE_GENERAL = 0.75
CONFIDENCE_DEFAULT_GROUNDED = 0.6
CONFIDENCE_CONFLICT_OR_MIXED = 0.4

AllowlistedReasonCode = Literal[
    "task_prompt",
    "workflow_ready",
    "incomplete_workflow",
    "conflicting_workflows",
    "missing_fields",
    "tool_unavailable",
    "general_cues",
    "project_cues",
    "mixed_cues",
    "default_grounded",
]

REASON_CODES: frozenset[str] = frozenset(
    {
        "task_prompt",
        "workflow_ready",
        "incomplete_workflow",
        "conflicting_workflows",
        "missing_fields",
        "tool_unavailable",
        "general_cues",
        "project_cues",
        "mixed_cues",
        "default_grounded",
    }
)
REASON_CODES_DISPLAY = str(sorted(REASON_CODES))

WORKFLOW_HINTS: frozenset[str] = frozenset({"test_design", "drive_export"})
WORKFLOW_HINTS_DISPLAY = str(sorted(WORKFLOW_HINTS))


class RoutingKind(StrEnum):
    """Sole intent vocabulary for turn routing."""

    TOOL_WORKFLOW = "tool_workflow"
    CLARIFICATION = "clarification"
    GROUNDED_ANSWER = "grounded_answer"
    GENERAL_ANSWER = "general_answer"


class WorkflowReadiness(StrEnum):
    """Whether a recognized workflow has the inputs needed to run."""

    READY = "ready"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class TurnRoutingRequest:
    """Inputs for one routing decision."""

    query: str
    history: Sequence[Message] = ()
    clarification_context: Mapping[str, object] | None = None
    conversation_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowSignalResult:
    """One pack/composition probe result for a recognized workflow.

    Attributes:
        workflow_hint: Allowlisted opaque workflow id.
        readiness: Ready to run vs needs clarification.
        reason: Allowlisted reason code.
        missing_fields: Allowlisted field keys only (no secrets/payloads).
        clarification_context: Structured context for a follow-up turn.
    """

    workflow_hint: str
    readiness: WorkflowReadiness
    reason: str
    missing_fields: tuple[str, ...] = ()
    clarification_context: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.workflow_hint not in WORKFLOW_HINTS:
            raise ApplicationValidationError(
                f"workflow_hint must be one of {WORKFLOW_HINTS_DISPLAY}"
            )
        if not isinstance(self.readiness, WorkflowReadiness):
            raise ApplicationValidationError(
                "readiness must be a WorkflowReadiness, "
                f"got {type(self.readiness).__name__}"
            )
        if self.reason not in REASON_CODES:
            raise ApplicationValidationError(
                f"reason must be one of {REASON_CODES_DISPLAY}"
            )
        if not isinstance(self.missing_fields, tuple):
            object.__setattr__(
                self, "missing_fields", tuple(self.missing_fields)
            )
        for field_name in self.missing_fields:
            if not isinstance(field_name, str) or not field_name.strip():
                raise ApplicationValidationError(
                    "missing_fields entries must be non-empty strings"
                )
        if self.clarification_context is not None:
            if not isinstance(self.clarification_context, Mapping):
                raise ApplicationValidationError(
                    "clarification_context must be a mapping"
                )
            object.__setattr__(
                self, "clarification_context", dict(self.clarification_context)
            )


WorkflowSignal = Callable[[TurnRoutingRequest], WorkflowSignalResult | None]


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Immutable routing decision for one chat turn.

    Attributes:
        kind: Routing intent (also the ``RunMeta.intent`` value).
        routing_confidence: Fixed heuristic score, not calibrated probability.
        ambiguous: True when conflict or mixed cues forced clarification.
        reason: Allowlisted reason code only.
        workflow_hint: Optional allowlisted workflow id.
        clarification_context: Structured follow-up context when clarifying.
    """

    kind: RoutingKind
    routing_confidence: float
    ambiguous: bool
    reason: str
    workflow_hint: str | None = None
    clarification_context: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RoutingKind):
            raise ApplicationValidationError(
                f"kind must be a RoutingKind, got {type(self.kind).__name__}"
            )
        if not isinstance(self.routing_confidence, float) or isinstance(
            self.routing_confidence, bool
        ):
            raise ApplicationValidationError(
                "routing_confidence must be a float, "
                f"got {type(self.routing_confidence).__name__}"
            )
        if not 0.0 <= self.routing_confidence <= 1.0:
            raise ApplicationValidationError(
                "routing_confidence must be between 0 and 1"
            )
        if not isinstance(self.ambiguous, bool):
            raise ApplicationValidationError(
                f"ambiguous must be a bool, got {type(self.ambiguous).__name__}"
            )
        if self.reason not in REASON_CODES:
            raise ApplicationValidationError(
                f"reason must be one of {REASON_CODES_DISPLAY}"
            )
        if self.workflow_hint is not None and self.workflow_hint not in WORKFLOW_HINTS:
            raise ApplicationValidationError(
                f"workflow_hint must be one of {WORKFLOW_HINTS_DISPLAY}"
            )
        if self.clarification_context is not None:
            if not isinstance(self.clarification_context, Mapping):
                raise ApplicationValidationError(
                    "clarification_context must be a mapping"
                )
            object.__setattr__(
                self, "clarification_context", dict(self.clarification_context)
            )


_PROJECT_CUES = re.compile(
    r"\b("
    r"docs?|documentation|readme|repository|repo|codebase|this\s+project|"
    r"in\s+this\s+repo|according\s+to|our\s+(?:docs|code|repo)|"
    r"source(?:s)?|catalog|ingested|knowledge\s+base|"
    r"(?:github\s+)?(?:issue|pr|pull\s+request)\b|"
    r"[\w.-]+/[\w.-]+#\d+"
    r")\b",
    re.IGNORECASE,
)

_GENERAL_CUES = re.compile(
    r"\b("
    r"brainstorm|creative|tagline|rewrite|rephrase|summarize\s+this\s+text|"
    r"draft\s+a\s+(?:poem|story|email)|role[\s-]?play|"
    r"generally\s+speaking|in\s+general|"
    r"ideas?\s+for\s+a\s+(?:coffee|brand|startup)"
    r")\b",
    re.IGNORECASE,
)


def has_project_cues(query: str) -> bool:
    """Return True when ``query`` carries project/docs grounding cues."""
    return _PROJECT_CUES.search(query) is not None


def _has_project_cues(query: str) -> bool:
    return has_project_cues(query)


def _has_general_cues(query: str) -> bool:
    return _GENERAL_CUES.search(query) is not None


def _collect_signals(
    request: TurnRoutingRequest,
    signals: Sequence[WorkflowSignal],
) -> tuple[WorkflowSignalResult, ...]:
    collected: list[WorkflowSignalResult] = []
    for probe in signals:
        result = probe(request)
        if result is not None:
            collected.append(result)
    return tuple(collected)


def _aggregate_signals(
    active: Sequence[WorkflowSignalResult],
) -> RoutingDecision | None:
    if not active:
        return None

    hints = {signal.workflow_hint for signal in active}
    if len(hints) > 1:
        return RoutingDecision(
            kind=RoutingKind.CLARIFICATION,
            routing_confidence=CONFIDENCE_CONFLICT_OR_MIXED,
            ambiguous=True,
            reason="conflicting_workflows",
        )

    incompletes = [
        s for s in active if s.readiness is WorkflowReadiness.INCOMPLETE
    ]
    readies = [s for s in active if s.readiness is WorkflowReadiness.READY]

    if incompletes and readies:
        return RoutingDecision(
            kind=RoutingKind.CLARIFICATION,
            routing_confidence=CONFIDENCE_CONFLICT_OR_MIXED,
            ambiguous=True,
            reason="conflicting_workflows",
        )

    if incompletes:
        primary = incompletes[0]
        reason = primary.reason
        if reason not in {
            "incomplete_workflow",
            "missing_fields",
            "tool_unavailable",
        }:
            reason = "incomplete_workflow"
        return RoutingDecision(
            kind=RoutingKind.CLARIFICATION,
            routing_confidence=CONFIDENCE_INCOMPLETE,
            ambiguous=False,
            reason=reason,
            workflow_hint=primary.workflow_hint,
            clarification_context=primary.clarification_context,
        )

    if len(readies) == 1:
        primary = readies[0]
        return RoutingDecision(
            kind=RoutingKind.TOOL_WORKFLOW,
            routing_confidence=CONFIDENCE_READY,
            ambiguous=False,
            reason="workflow_ready",
            workflow_hint=primary.workflow_hint,
        )

    if len(readies) > 1:
        return RoutingDecision(
            kind=RoutingKind.CLARIFICATION,
            routing_confidence=CONFIDENCE_CONFLICT_OR_MIXED,
            ambiguous=True,
            reason="conflicting_workflows",
        )

    return None


def _classify_cues(query: str) -> RoutingDecision:
    project = _has_project_cues(query)
    general = _has_general_cues(query)
    if project and general:
        return RoutingDecision(
            kind=RoutingKind.CLARIFICATION,
            routing_confidence=CONFIDENCE_CONFLICT_OR_MIXED,
            ambiguous=True,
            reason="mixed_cues",
        )
    if general:
        return RoutingDecision(
            kind=RoutingKind.GENERAL_ANSWER,
            routing_confidence=CONFIDENCE_GENERAL,
            ambiguous=False,
            reason="general_cues",
        )
    if project:
        return RoutingDecision(
            kind=RoutingKind.GROUNDED_ANSWER,
            routing_confidence=CONFIDENCE_DEFAULT_GROUNDED,
            ambiguous=False,
            reason="project_cues",
        )
    return RoutingDecision(
        kind=RoutingKind.GROUNDED_ANSWER,
        routing_confidence=CONFIDENCE_DEFAULT_GROUNDED,
        ambiguous=False,
        reason="default_grounded",
    )


def classify_turn(
    query: str | TurnRoutingRequest,
    *,
    history: Sequence[Message] = (),
    signals: Sequence[WorkflowSignal] = (),
    clarification_context: Mapping[str, object] | None = None,
    conversation_id: str | None = None,
) -> RoutingDecision:
    """Classify one General-mode turn before retrieval.

    Raw chat history alone never promotes a short affirmative to
    ``tool_workflow``. Workflow readiness is entirely determined by injected
    signals (which may consult structured ``clarification_context`` plus newly
    supplied fields in ``query``).

    Args:
        query: Current user message, or a full :class:`TurnRoutingRequest`.
        history: Prior thread messages (not used to auto-promote tools).
        signals: Injected workflow probes.
        clarification_context: Structured prior clarification payload.
        conversation_id: Trusted conversation id for readiness checks.

    Returns:
        RoutingDecision for the turn.
    """
    if isinstance(query, TurnRoutingRequest):
        request = query
    else:
        if not isinstance(query, str):
            raise ApplicationValidationError(
                f"query must be a string, got {type(query).__name__}"
            )
        request = TurnRoutingRequest(
            query=query,
            history=history,
            clarification_context=clarification_context,
            conversation_id=conversation_id,
        )
    # History is forwarded to signals only; this router never promotes bare
    # affirmatives from raw history to tool_workflow.
    active = _collect_signals(request, signals)
    aggregated = _aggregate_signals(active)
    if aggregated is not None:
        return aggregated
    return _classify_cues(request.query)


class TurnRouter:
    """Callable router that aggregates injected workflow signals and cues."""

    def __init__(self, signals: Sequence[WorkflowSignal] = ()) -> None:
        self._signals = tuple(signals)

    def classify(
        self,
        query: str | TurnRoutingRequest,
        *,
        history: Sequence[Message] = (),
        clarification_context: Mapping[str, object] | None = None,
        conversation_id: str | None = None,
        signals: Sequence[WorkflowSignal] | None = None,
    ) -> RoutingDecision:
        """Classify ``query`` using instance signals merged with any overrides."""
        probes = self._signals if signals is None else tuple(signals)
        return classify_turn(
            query,
            history=history,
            signals=probes,
            clarification_context=clarification_context,
            conversation_id=conversation_id,
        )


__all__ = [
    "CONFIDENCE_CONFLICT_OR_MIXED",
    "CONFIDENCE_DEFAULT_GROUNDED",
    "CONFIDENCE_GENERAL",
    "CONFIDENCE_INCOMPLETE",
    "CONFIDENCE_READY",
    "REASON_CODES",
    "REASON_CODES_DISPLAY",
    "RoutingDecision",
    "RoutingKind",
    "TurnRouter",
    "TurnRoutingRequest",
    "WORKFLOW_HINTS",
    "WORKFLOW_HINTS_DISPLAY",
    "WorkflowReadiness",
    "WorkflowSignal",
    "WorkflowSignalResult",
    "classify_turn",
    "has_project_cues",
]
