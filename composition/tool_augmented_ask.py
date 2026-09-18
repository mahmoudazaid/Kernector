"""Chat-time turn routing layered over grounded ask, general ask, and tools.

``AskKnowledge`` cannot make pack workflow decisions: ``application/`` may not
import ``packs``. :class:`TurnRouter` owns the routing decision; composition
injects :class:`~application.turn_routing.WorkflowSignal` probes and builds
handoffs / tool runs **after** the decision.

Request-id correlation is owned by :class:`composition.correlated_ask.CorrelatedAsk`
outside this router so zero-pack chats are observed the same way.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import logging
from typing import Protocol

from application.contracts import AskRequest, AskResponse, Citation, InvokeToolResponse, RunMeta
from application.errors import InsufficientEvidenceError
from application.grounded_rag_policy import INSUFFICIENT_KNOWLEDGE_ANSWER
from application.observability import current_request_id, log_operation
from application.turn_routing import (
    RoutingDecision,
    RoutingKind,
    TurnRouter,
    TurnRoutingRequest,
    WorkflowSignal,
)
from composition.clarification_context import ClarificationContextStore
from composition.software_delivery_tools import SoftwareDeliveryRunView
from composition.workflow_signals import clarification_answer_for

logger = logging.getLogger(__name__)


def _merge_run(
    run: RunMeta | None,
    *,
    outcome: str,
    path: str,
    pack: str | None = None,
    tools: Sequence[str] = (),
    prompt_key: str | None = None,
    hit_count: int | None = None,
    citation_count: int | None = None,
    response_style: object = None,
    intent: str | None = None,
    routing_confidence: float | None = None,
    ambiguous: bool | None = None,
) -> RunMeta:
    """Overlay route fields onto an existing or empty ``RunMeta``."""
    base = run if run is not None else RunMeta()
    updates: dict[str, object] = {
        "outcome": outcome,
        "path": path,
        "request_id": base.request_id or current_request_id(),
    }
    if pack is not None:
        updates["pack"] = pack
    if tools:
        updates["tools"] = tuple(tools)
    if prompt_key is not None:
        updates["prompt_key"] = prompt_key
    if hit_count is not None:
        updates["hit_count"] = hit_count
    if citation_count is not None:
        updates["citation_count"] = citation_count
    style_value = getattr(response_style, "value", response_style)
    if isinstance(style_value, str) and style_value.strip():
        updates["response_style"] = style_value
    if intent is not None:
        updates["intent"] = intent
    if routing_confidence is not None:
        updates["routing_confidence"] = routing_confidence
    if ambiguous is not None:
        updates["ambiguous"] = ambiguous
    return replace(base, **updates)


def _tool_names(outputs: Sequence[InvokeToolResponse]) -> tuple[str, ...]:
    return tuple(output.tool_name for output in outputs)


def _routing_fields(decision: RoutingDecision) -> dict[str, object]:
    return {
        "intent": decision.kind.value,
        "routing_confidence": decision.routing_confidence,
        "ambiguous": decision.ambiguous,
    }


class GroundedAsk(Protocol):
    """The ask seam presentation holds, whether or not tools are wired."""

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        """Answer ``request``, optionally applying generation ``settings``."""


@dataclass(frozen=True, slots=True)
class ToolRunOutcome:
    """What one completed tool run contributes to an answer.

    Attributes:
        answer (str): Deterministic text built from typed results — never a
            second model call for tool chains.
        citations (tuple[Citation, ...]): Provenance for the evidence the run was
            grounded in.
        tool_outputs (tuple[InvokeToolResponse, ...]): One opaque entry per
            successful tool invocation, in call order.
        run (RunMeta | None): Observability for the tool turn.
        run_view (SoftwareDeliveryRunView | None): Typed presentation projection
            for Software Delivery tool chains.
        pending_approval: Optional HITL projection when a tool awaits approval.
    """

    answer: str
    citations: tuple[Citation, ...] = ()
    tool_outputs: tuple[InvokeToolResponse, ...] = ()
    run: RunMeta | None = None
    run_view: SoftwareDeliveryRunView | None = None
    pending_approval: object | None = None


class ToolSelection(Protocol):
    """A pack's answer to "which workflow does this query ask for?"."""

    generate_tests: bool
    output_style: str


class ToolRunner(Protocol):
    """Retrieve evidence for a target and run the selected chain over it."""

    def run(
        self,
        target: str,
        *,
        generate_tests: bool = True,
        output_style: str = "steps",
        conversation_id: str | None = None,
        response_style: object = None,
        need_evidence: bool = True,
    ) -> ToolRunOutcome:
        """Run the chain and project its typed results onto one outcome."""


SelectToolIntent = Callable[[str], ToolSelection | None]
TestDesignHandoffBuilder = Callable[[AskRequest], object | None]


class ToolAugmentedAsk:
    """Route a chat query via :class:`TurnRouter`, then execute the path.

    Args:
        ask: Grounded RAG path (also task_prompt delegation).
        runner: Tool/workflow runner for ``tool_workflow`` (Drive export).
        signals: Injected workflow probes (Test Design, Drive, …).
        ask_general: Labelled non-RAG path for ``general_answer``.
        pack_id: Pack identifier logged on tool routes.
        build_test_design_handoff: Builds handoff view after ``test_design`` ready.
        select: Legacy intent selector used only when ``signals`` is empty
            (unit-test compat for pre-router scaffolding doubles).
        clarification_context_store: Optional conversation-scoped prior clarify
            context (get on route; set on clarify; clear on other paths).
        grounded_ask: Optional agentic grounded path (retrieve tool then answer).
            When set, ``GROUNDED_ANSWER`` uses this instead of ``ask``.
    """

    def __init__(
        self,
        ask: GroundedAsk,
        *,
        runner: ToolRunner,
        signals: Sequence[WorkflowSignal] = (),
        ask_general: GroundedAsk | None = None,
        pack_id: str | None = None,
        build_test_design_handoff: TestDesignHandoffBuilder | None = None,
        select: SelectToolIntent | None = None,
        clarification_context_store: ClarificationContextStore | None = None,
        grounded_ask: GroundedAsk | None = None,
    ) -> None:
        self._ask = ask
        self._grounded_ask = grounded_ask
        self._runner = runner
        self._ask_general = ask_general
        self._pack_id = pack_id
        self._build_test_design_handoff = build_test_design_handoff
        self._select = select
        self._clarification_context_store = clarification_context_store
        self._router = TurnRouter(signals=signals)
        self._use_router = bool(signals) or ask_general is not None
        self._pending_run_view: SoftwareDeliveryRunView | None = None
        self._pending_workflow_action: object | None = None
        self._pending_clarification_context: Mapping[str, object] | None = None

    def consume_tool_run_view(self) -> SoftwareDeliveryRunView | None:
        """Return and clear the typed view from the last tools-path execute."""
        view = self._pending_run_view
        self._pending_run_view = None
        return view

    def consume_workflow_action(self) -> object | None:
        """Return and clear a Test Design (or similar) handoff action."""
        action = self._pending_workflow_action
        self._pending_workflow_action = None
        return action

    def consume_clarification_context(self) -> Mapping[str, object] | None:
        """Return structured clarification context from the last clarify turn."""
        context = self._pending_clarification_context
        self._pending_clarification_context = None
        return context

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        """Apply task_prompt pre-rule, then route and dispatch."""
        self._pending_run_view = None
        self._pending_workflow_action = None
        self._pending_clarification_context = None

        if request.prompt_key is not None:
            return self._delegate_task_prompt(request, settings)

        if self._use_router:
            return self._execute_routed(request, settings)
        return self._execute_legacy_select(request, settings)

    def _delegate_task_prompt(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None,
    ) -> AskResponse:
        response = self._ask.execute(request, settings)
        log_operation(
            logger,
            operation="ask_turn",
            outcome="delegated",
            path="task_prompt",
            prompt_key=request.prompt_key,
        )
        return AskResponse(
            answer=response.answer,
            citations=response.citations,
            tool_outputs=response.tool_outputs,
            generation_hits=response.generation_hits,
            run=_merge_run(
                response.run,
                outcome=(
                    response.run.outcome
                    if response.run and response.run.outcome
                    else "success"
                ),
                path="task_prompt",
                prompt_key=request.prompt_key,
                intent=None,
            ),
        )

    def _execute_routed(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None,
    ) -> AskResponse:
        prior = None
        if self._clarification_context_store is not None:
            prior = self._clarification_context_store.get(request.conversation_id)
        decision = self._router.classify(
            TurnRoutingRequest(
                query=request.query,
                history=request.history,
                clarification_context=prior,
                conversation_id=request.conversation_id,
            )
        )
        if decision.kind is RoutingKind.CLARIFICATION:
            return self._clarification_response(decision, request)
        if decision.kind is RoutingKind.GENERAL_ANSWER:
            self._clear_clarification_context(request.conversation_id)
            return self._general_response(decision, request, settings)
        if decision.kind is RoutingKind.TOOL_WORKFLOW:
            self._clear_clarification_context(request.conversation_id)
            return self._tool_workflow_response(decision, request, settings)
        self._clear_clarification_context(request.conversation_id)
        return self._grounded_response(decision, request, settings)

    def _set_clarification_context(
        self,
        conversation_id: str | None,
        context: Mapping[str, object] | None,
    ) -> None:
        if self._clarification_context_store is None:
            return
        self._clarification_context_store.set(conversation_id, context)

    def _clear_clarification_context(self, conversation_id: str | None) -> None:
        self._set_clarification_context(conversation_id, None)

    def _clarification_response(
        self,
        decision: RoutingDecision,
        request: AskRequest,
    ) -> AskResponse:
        answer = clarification_answer_for(decision.reason, decision.workflow_hint)
        self._pending_clarification_context = decision.clarification_context
        self._set_clarification_context(
            request.conversation_id, decision.clarification_context
        )
        log_operation(
            logger,
            operation="ask_turn",
            outcome="success",
            path="clarification",
            intent=decision.kind.value,
            reason=decision.reason,
        )
        return AskResponse(
            answer=answer,
            citations=(),
            generation_hits=(),
            run=_merge_run(
                None,
                outcome="success",
                path="clarification",
                response_style=request.response_style,
                **_routing_fields(decision),
            ),
        )

    def _general_response(
        self,
        decision: RoutingDecision,
        request: AskRequest,
        settings: Mapping[str, object] | None,
    ) -> AskResponse:
        if self._ask_general is None:
            return self._grounded_response(decision, request, settings)
        response = self._ask_general.execute(request, settings)
        log_operation(
            logger,
            operation="ask_turn",
            outcome="success",
            path="general_answer",
            intent=decision.kind.value,
        )
        return AskResponse(
            answer=response.answer,
            citations=(),
            generation_hits=(),
            run=_merge_run(
                response.run,
                outcome="success",
                path="general_answer",
                response_style=request.response_style,
                **_routing_fields(decision),
            ),
        )

    def _grounded_response(
        self,
        decision: RoutingDecision,
        request: AskRequest,
        settings: Mapping[str, object] | None,
    ) -> AskResponse:
        grounded = self._grounded_ask if self._grounded_ask is not None else self._ask
        response = grounded.execute(request, settings)
        log_operation(
            logger, operation="ask_turn", outcome="delegated", path="rag"
        )
        return AskResponse(
            answer=response.answer,
            citations=response.citations,
            tool_outputs=response.tool_outputs,
            generation_hits=response.generation_hits,
            run=_merge_run(
                response.run,
                outcome=(
                    response.run.outcome
                    if response.run and response.run.outcome
                    else "success"
                ),
                path="rag",
                **_routing_fields(decision),
            ),
        )

    def _tool_workflow_response(
        self,
        decision: RoutingDecision,
        request: AskRequest,
        settings: Mapping[str, object] | None,
    ) -> AskResponse:
        del settings
        if decision.workflow_hint == "test_design":
            return self._test_design_handoff(decision, request)
        return self._run_tools(decision, request)

    def _test_design_handoff(
        self,
        decision: RoutingDecision,
        request: AskRequest,
    ) -> AskResponse:
        if self._build_test_design_handoff is None:
            return AskResponse(
                answer=clarification_answer_for("tool_unavailable", "test_design"),
                citations=(),
                generation_hits=(),
                run=_merge_run(
                    None,
                    outcome="success",
                    path="clarification",
                    intent=RoutingKind.CLARIFICATION.value,
                    routing_confidence=decision.routing_confidence,
                    ambiguous=False,
                    response_style=request.response_style,
                ),
            )
        handoff = self._build_test_design_handoff(request)
        if handoff is None:
            return AskResponse(
                answer=clarification_answer_for("tool_unavailable", "test_design"),
                citations=(),
                generation_hits=(),
                run=_merge_run(
                    None,
                    outcome="success",
                    path="clarification",
                    intent=RoutingKind.CLARIFICATION.value,
                    routing_confidence=decision.routing_confidence,
                    ambiguous=False,
                    response_style=request.response_style,
                ),
            )
        action = getattr(handoff, "action", None)
        answer = getattr(handoff, "answer", "")
        self._pending_workflow_action = action
        log_operation(
            logger,
            operation="ask_turn",
            outcome="success",
            path="tools",
            intent=decision.kind.value,
            pack=self._pack_id,
        )
        return AskResponse(
            answer=answer,
            citations=(),
            generation_hits=(),
            run=_merge_run(
                None,
                outcome="success",
                path="tools",
                pack=self._pack_id,
                response_style=request.response_style,
                **_routing_fields(decision),
            ),
        )

    def _run_tools(
        self,
        decision: RoutingDecision,
        request: AskRequest,
    ) -> AskResponse:
        try:
            # Drive export is ready from routing + draft titles. Affirmative
            # follow-ups ("yes") must not become the retrieve target, and the
            # export path does not need RAG evidence.
            if decision.workflow_hint == "drive_export":
                outcome = self._runner.run(
                    "Export selected Test Design titles to Google Drive",
                    generate_tests=True,
                    output_style="steps",
                    conversation_id=request.conversation_id,
                    response_style=request.response_style,
                    need_evidence=False,
                )
            else:
                outcome = self._runner.run(
                    request.query,
                    generate_tests=True,
                    output_style="steps",
                    conversation_id=request.conversation_id,
                    response_style=request.response_style,
                )
        except InsufficientEvidenceError:
            log_operation(
                logger,
                operation="ask_turn",
                outcome="insufficient",
                path="tools",
                pack=self._pack_id,
            )
            return AskResponse(
                answer=INSUFFICIENT_KNOWLEDGE_ANSWER,
                generation_hits=(),
                run=_merge_run(
                    None,
                    outcome="insufficient",
                    path="tools",
                    pack=self._pack_id,
                    hit_count=0,
                    citation_count=0,
                    response_style=request.response_style,
                    **_routing_fields(decision),
                ),
            )
        log_operation(
            logger,
            operation="ask_turn",
            outcome="success",
            path="tools",
            pack=self._pack_id,
        )
        self._pending_run_view = outcome.run_view
        if (
            outcome.pending_approval is not None
            and outcome.run_view is not None
            and getattr(outcome.run_view, "pending_approval", None) is None
        ):
            self._pending_run_view = replace(
                outcome.run_view, pending_approval=outcome.pending_approval
            )
        return AskResponse(
            answer=outcome.answer,
            citations=outcome.citations,
            tool_outputs=outcome.tool_outputs,
            generation_hits=(),
            run=_merge_run(
                outcome.run,
                outcome="success",
                path="tools",
                pack=self._pack_id,
                tools=_tool_names(outcome.tool_outputs),
                response_style=request.response_style,
                **_routing_fields(decision),
            ),
        )

    def _execute_legacy_select(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None,
    ) -> AskResponse:
        """Pre-router select→tools else RAG path (unit-test doubles)."""
        selection = None if self._select is None else self._select(request.query)
        if selection is None:
            response = self._ask.execute(request, settings)
            log_operation(
                logger, operation="ask_turn", outcome="delegated", path="rag"
            )
            return AskResponse(
                answer=response.answer,
                citations=response.citations,
                tool_outputs=response.tool_outputs,
                generation_hits=response.generation_hits,
                run=_merge_run(
                    response.run,
                    outcome=(
                        response.run.outcome
                        if response.run and response.run.outcome
                        else "success"
                    ),
                    path="rag",
                ),
            )

        try:
            outcome = self._runner.run(
                request.query,
                generate_tests=selection.generate_tests,
                output_style=selection.output_style,
                conversation_id=request.conversation_id,
                response_style=request.response_style,
            )
        except InsufficientEvidenceError:
            log_operation(
                logger,
                operation="ask_turn",
                outcome="insufficient",
                path="tools",
                pack=self._pack_id,
            )
            return AskResponse(
                answer=INSUFFICIENT_KNOWLEDGE_ANSWER,
                generation_hits=(),
                run=_merge_run(
                    None,
                    outcome="insufficient",
                    path="tools",
                    pack=self._pack_id,
                    hit_count=0,
                    citation_count=0,
                    response_style=request.response_style,
                ),
            )
        log_operation(
            logger,
            operation="ask_turn",
            outcome="success",
            path="tools",
            pack=self._pack_id,
        )
        self._pending_run_view = outcome.run_view
        if (
            outcome.pending_approval is not None
            and outcome.run_view is not None
            and getattr(outcome.run_view, "pending_approval", None) is None
        ):
            self._pending_run_view = replace(
                outcome.run_view, pending_approval=outcome.pending_approval
            )
        return AskResponse(
            answer=outcome.answer,
            citations=outcome.citations,
            tool_outputs=outcome.tool_outputs,
            generation_hits=(),
            run=_merge_run(
                outcome.run,
                outcome="success",
                path="tools",
                pack=self._pack_id,
                tools=_tool_names(outcome.tool_outputs),
                response_style=request.response_style,
            ),
        )
