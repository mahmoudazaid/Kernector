"""Chat-time tool and analysis selection layered over the grounded ask path.

``AskKnowledge`` cannot make this decision: ``application/`` may not import
``packs``, and the vocabulary that recognises a domain workflow request is
pack-owned. So the routing lives here, in the one layer already allowed to join
both — the "thin composition wrapper" the story names.

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
from composition.software_delivery_tools import SoftwareDeliveryRunView

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
    return replace(base, **updates)


def _tool_names(outputs: Sequence[InvokeToolResponse]) -> tuple[str, ...]:
    return tuple(output.tool_name for output in outputs)


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
    """What one completed tool or analysis run contributes to an answer.

    Attributes:
        answer (str): Deterministic text built from typed results — never a
            second model call for tool chains; analysis already produced its
            structured view before formatting.
        citations (tuple[Citation, ...]): Provenance for the evidence the run was
            grounded in.
        tool_outputs (tuple[InvokeToolResponse, ...]): One opaque entry per
            successful tool invocation, in call order. Empty for analysis.
        run (RunMeta | None): Observability for a model call made during the
            run. Tool chains leave this ``None``; requirements analysis projects
            ``AskResult`` metadata here.
        run_view (SoftwareDeliveryRunView | None): Typed presentation projection
            for Software Delivery tool chains. Not placed on ``AskResponse``;
            callers consume it via the composition side path. Analysis and RAG
            leave this ``None``.
    """

    answer: str
    citations: tuple[Citation, ...] = ()
    tool_outputs: tuple[InvokeToolResponse, ...] = ()
    run: RunMeta | None = None
    run_view: SoftwareDeliveryRunView | None = None


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
    ) -> ToolRunOutcome:
        """Run the chain and project its typed results onto one outcome."""


class AnalysisRunner(Protocol):
    """Run requirements analysis and project the view onto one outcome."""

    def run(self, requirements: str) -> ToolRunOutcome:
        """Analyze ``requirements`` and return a chat-ready outcome."""


SelectToolIntent = Callable[[str], ToolSelection | None]


class ToolAugmentedAsk:
    """Route a chat query to a domain workflow, or to grounded RAG.

    Args:
        ask (GroundedAsk): The ordinary grounded path, used verbatim whenever no
            intent matches.
        runner (ToolRunner): Retrieves evidence and runs the tool chain for a
            matched generate/risk intent.
        select (SelectToolIntent): The pack's deterministic intent policy.
        analysis_runner (AnalysisRunner | None): Requirements analysis path when
            the pack enables it; absent means analysis intents fall through to
            grounded RAG.
        pack_id (str | None): Pack identifier logged on tool/analysis routes.
    """

    def __init__(
        self,
        ask: GroundedAsk,
        *,
        runner: ToolRunner,
        select: SelectToolIntent,
        analysis_runner: AnalysisRunner | None = None,
        pack_id: str | None = None,
    ) -> None:
        self._ask = ask
        self._runner = runner
        self._select = select
        self._analysis_runner = analysis_runner
        self._pack_id = pack_id
        self._pending_run_view: SoftwareDeliveryRunView | None = None

    def consume_tool_run_view(self) -> SoftwareDeliveryRunView | None:
        """Return and clear the typed view from the last tools-path execute.

        Carrier beside ``AskResponse``: presentation reads this after ``execute``
        so typed views never enter the application contract.
        """
        view = self._pending_run_view
        self._pending_run_view = None
        return view

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        """Run the workflow the query names, or fall through to grounded RAG.

        ``request.history`` is deliberately not forwarded to the tool or analysis
        paths: both are grounded in retrieved evidence, not in the conversation.

        An empty corpus answers with the grounded path's own
        insufficient-knowledge sentence rather than a tool-flavoured variant —
        one vocabulary for "I don't know", whichever route the turn took.

        Selection runs only in General mode (``prompt_key is None``). A selected
        task prompt delegates the original ``AskRequest``, history, and
        generation settings unchanged to ``AskKnowledge`` — routing never moves
        into Streamlit.

        Delegation to ``AskKnowledge`` logs ``outcome=delegated``; the nested ask
        emits the terminal ``success`` / ``insufficient`` / ``error`` event.
        Tool and analysis paths log their own terminal outcomes.
        """
        self._pending_run_view = None
        if request.prompt_key is not None:
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
                run=_merge_run(
                    response.run,
                    outcome=response.run.outcome if response.run and response.run.outcome else "success",
                    path="task_prompt",
                    prompt_key=request.prompt_key,
                ),
            )
        selection = self._select(request.query)
        if selection is None:
            response = self._ask.execute(request, settings)
            log_operation(
                logger, operation="ask_turn", outcome="delegated", path="rag"
            )
            return AskResponse(
                answer=response.answer,
                citations=response.citations,
                tool_outputs=response.tool_outputs,
                run=_merge_run(
                    response.run,
                    outcome=response.run.outcome if response.run and response.run.outcome else "success",
                    path="rag",
                ),
            )

        if getattr(selection, "analyze_requirements", False):
            if self._analysis_runner is None:
                response = self._ask.execute(request, settings)
                log_operation(
                    logger, operation="ask_turn", outcome="delegated", path="rag"
                )
                return AskResponse(
                    answer=response.answer,
                    citations=response.citations,
                    tool_outputs=response.tool_outputs,
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
            target = getattr(selection, "analysis_target", "") or request.query
            try:
                outcome = self._analysis_runner.run(target)
            except InsufficientEvidenceError:
                log_operation(
                    logger,
                    operation="ask_turn",
                    outcome="insufficient",
                    path="analysis",
                    pack=self._pack_id,
                )
                return AskResponse(
                    answer=INSUFFICIENT_KNOWLEDGE_ANSWER,
                    run=_merge_run(
                        None,
                        outcome="insufficient",
                        path="analysis",
                        pack=self._pack_id,
                        hit_count=0,
                    ),
                )
            log_operation(
                logger,
                operation="ask_turn",
                outcome="success",
                path="analysis",
                pack=self._pack_id,
            )
            return AskResponse(
                answer=outcome.answer,
                citations=outcome.citations,
                tool_outputs=outcome.tool_outputs,
                run=_merge_run(
                    outcome.run,
                    outcome="success",
                    path="analysis",
                    pack=self._pack_id,
                    tools=_tool_names(outcome.tool_outputs),
                ),
            )

        try:
            outcome = self._runner.run(
                request.query,
                generate_tests=selection.generate_tests,
                output_style=selection.output_style,
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
                run=_merge_run(
                    None,
                    outcome="insufficient",
                    path="tools",
                    pack=self._pack_id,
                    hit_count=0,
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
        return AskResponse(
            answer=outcome.answer,
            citations=outcome.citations,
            tool_outputs=outcome.tool_outputs,
            run=_merge_run(
                outcome.run,
                outcome="success",
                path="tools",
                pack=self._pack_id,
                tools=_tool_names(outcome.tool_outputs),
            ),
        )
