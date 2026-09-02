"""Chat-time tool and analysis selection layered over the grounded ask path.

``AskKnowledge`` cannot make this decision: ``application/`` may not import
``packs``, and the vocabulary that recognises a domain workflow request is
pack-owned. So the routing lives here, in the one layer already allowed to join
both — the "thin composition wrapper" the story names.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from application.contracts import AskRequest, AskResponse, Citation, InvokeToolResponse, RunMeta
from application.errors import InsufficientEvidenceError
from application.grounded_rag_policy import INSUFFICIENT_KNOWLEDGE_ANSWER


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
    """

    answer: str
    citations: tuple[Citation, ...] = ()
    tool_outputs: tuple[InvokeToolResponse, ...] = ()
    run: RunMeta | None = None


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
    """

    def __init__(
        self,
        ask: GroundedAsk,
        *,
        runner: ToolRunner,
        select: SelectToolIntent,
        analysis_runner: AnalysisRunner | None = None,
    ) -> None:
        self._ask = ask
        self._runner = runner
        self._select = select
        self._analysis_runner = analysis_runner

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
        """
        if request.prompt_key is not None:
            return self._ask.execute(request, settings)
        selection = self._select(request.query)
        if selection is None:
            return self._ask.execute(request, settings)

        if getattr(selection, "analyze_requirements", False):
            if self._analysis_runner is None:
                return self._ask.execute(request, settings)
            target = getattr(selection, "analysis_target", "") or request.query
            try:
                outcome = self._analysis_runner.run(target)
            except InsufficientEvidenceError:
                return AskResponse(answer=INSUFFICIENT_KNOWLEDGE_ANSWER)
            return AskResponse(
                answer=outcome.answer,
                citations=outcome.citations,
                tool_outputs=outcome.tool_outputs,
                run=outcome.run,
            )

        try:
            outcome = self._runner.run(
                request.query,
                generate_tests=selection.generate_tests,
                output_style=selection.output_style,
            )
        except InsufficientEvidenceError:
            return AskResponse(answer=INSUFFICIENT_KNOWLEDGE_ANSWER)
        return AskResponse(
            answer=outcome.answer,
            citations=outcome.citations,
            tool_outputs=outcome.tool_outputs,
            run=outcome.run,
        )
