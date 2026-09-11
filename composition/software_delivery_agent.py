"""Agent-backed Software Delivery orchestrate for chat-time tool runs.

When ``SOFTWARE_DELIVERY_AGENT_LOOP`` is on, composition injects this orchestrate
in place of the deterministic #170 chain. Pack imports stay lazy so
``import composition`` never loads a pack.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from application.run_tool_agent import RunToolAgent
from application.untrusted_text import AGENT_BOUNDARY
from composition.software_delivery_chat import OpaqueInvoke, Orchestrate
from domain.knowledge import ScoredChunk
from domain.ports import Tool, ToolCallingAgent

_RISK_TOOL = "software_delivery.risk_score"
_GENERATE_TOOL = "software_delivery.generate_test_cases"
_EXPORT_TOOL = "software_delivery.export_test_cases_markdown"

_DEFAULT_MAX_STEPS = 8

_FIXED_ARGS_NOTE = (
    " Arguments are fixed by the caller from the evidence bundle; "
    "do not invent or rely on tool parameters."
)
_EXPORT_BEFORE_GENERATE = (
    "Generate test cases first before exporting Markdown."
)
_TRUNCATED_NOTE = " The agent stopped early before completing the requested tools."


@dataclass(frozen=True, slots=True)
class _BoundTool:
    """Domain ``Tool`` whose body calls opaque invoke with closed-over args."""

    _name: str
    _description: str
    _invoke: OpaqueInvoke
    _arguments: Mapping[str, object]
    _on_result: object  # Callable[[str], None]

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def run(self, arguments: Mapping[str, object]) -> str:
        del arguments  # Closed-over evidence/args; agent schema is empty.
        result = self._invoke(self._name, self._arguments)
        self._on_result(result)  # type: ignore[operator]
        return result


def build_agent_orchestrate(
    agent: ToolCallingAgent,
    *,
    max_steps: int = _DEFAULT_MAX_STEPS,
) -> Orchestrate:
    """Return an ``orchestrate`` callable backed by ``agent``.

    Args:
        agent (ToolCallingAgent): Port that runs the tool-calling loop.
        max_steps (int): Hard model-step cap forwarded to the agent.

    Returns:
        Orchestrate: Callable matching the Software Delivery chat orchestrate seam.
    """
    run_agent = RunToolAgent(agent)

    def orchestrate(
        *,
        target: str,
        hits: Sequence[ScoredChunk],
        generate_tests: bool,
        output_style: str,
        invoke: OpaqueInvoke,
    ):
        from packs.software_delivery.evidence_bundle import (
            evidence_bundle_from_hits,
            export_tool_arguments,
            generate_test_tool_arguments,
            risk_tool_arguments,
        )
        from packs.software_delivery.orchestration_contracts import (
            ExportMarkdownOutcome,
            GenerateTestsOutcome,
            OrchestrateSoftwareDeliveryResponse,
            RiskScoreOutcome,
            SoftwareDeliveryOutcome,
        )
        from packs.software_delivery.tool_results import (
            parse_risk_assessment_result,
            parse_test_generation_result,
            serialize_test_generation_for_export,
        )

        evidence = evidence_bundle_from_hits(hits)
        outcomes: list[SoftwareDeliveryOutcome] = []

        def on_risk(raw: str) -> None:
            outcomes.append(RiskScoreOutcome(parse_risk_assessment_result(raw)))

        def on_generate(raw: str) -> None:
            outcomes.append(
                GenerateTestsOutcome(parse_test_generation_result(raw))
            )

        def on_export(raw: str) -> None:
            outcomes.append(ExportMarkdownOutcome(raw))

        tools: list[Tool] = [
            _BoundTool(
                _RISK_TOOL,
                "Score software-delivery risk from the evidence bundle."
                + _FIXED_ARGS_NOTE,
                invoke,
                risk_tool_arguments(target, evidence),
                on_risk,
            )
        ]
        if generate_tests:
            tools.append(
                _BoundTool(
                    _GENERATE_TOOL,
                    "Generate test cases from the evidence bundle."
                    + _FIXED_ARGS_NOTE,
                    invoke,
                    generate_test_tool_arguments(target, evidence, output_style),
                    on_generate,
                )
            )

            def export_args() -> Mapping[str, object] | None:
                generated = _latest_generation(outcomes)
                if generated is None:
                    return None
                return export_tool_arguments(
                    serialize_test_generation_for_export(generated.result)
                )

            tools.append(
                _LazyExportTool(
                    invoke=invoke,
                    arguments_factory=export_args,
                    on_result=on_export,
                )
            )

        goal = _agent_goal(target=target, hits=hits, generate_tests=generate_tests)
        turn = run_agent.execute(goal, tools, max_steps=max_steps)

        return OrchestrateSoftwareDeliveryResponse(
            summary=_summary_from_outcomes(
                outcomes,
                generate_tests=generate_tests,
                truncated=turn.truncated,
            ),
            outcomes=tuple(outcomes),
        )

    return orchestrate


@dataclass(frozen=True, slots=True)
class _LazyExportTool:
    """Export tool that builds arguments after generate has run."""

    invoke: OpaqueInvoke
    arguments_factory: object  # Callable[[], Mapping[str, object] | None]
    on_result: object  # Callable[[str], None]
    _name: str = _EXPORT_TOOL
    _description: str = (
        "Export generated test cases as Markdown." + _FIXED_ARGS_NOTE
    )

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def run(self, arguments: Mapping[str, object]) -> str:
        del arguments
        args = self.arguments_factory()  # type: ignore[operator]
        if args is None:
            return _EXPORT_BEFORE_GENERATE
        result = self.invoke(self._name, args)
        self.on_result(result)  # type: ignore[operator]
        return result


def _latest_generation(outcomes: Sequence[object]) -> object | None:
    from packs.software_delivery.orchestration_contracts import GenerateTestsOutcome

    for outcome in reversed(outcomes):
        if isinstance(outcome, GenerateTestsOutcome):
            return outcome
    return None


def _summary_from_outcomes(
    outcomes: Sequence[object],
    *,
    generate_tests: bool = False,
    truncated: bool = False,
) -> str:
    """Author the reply summary from tools that actually ran."""
    from packs.software_delivery.orchestration_contracts import (
        ExportMarkdownOutcome,
        GenerateTestsOutcome,
        RiskScoreOutcome,
    )
    from packs.software_delivery.orchestration_policy import (
        SoftwareDeliveryIntent,
        orchestration_summary,
    )

    has_risk = any(isinstance(o, RiskScoreOutcome) for o in outcomes)
    has_generate = any(isinstance(o, GenerateTestsOutcome) for o in outcomes)
    has_export = any(isinstance(o, ExportMarkdownOutcome) for o in outcomes)

    if generate_tests and not has_generate:
        if has_risk:
            summary = (
                "Scored software-delivery risk from the evidence bundle, "
                "but could not generate test cases."
            )
        else:
            summary = "No software-delivery tools were invoked."
    elif has_risk and has_generate and has_export:
        summary = orchestration_summary(
            SoftwareDeliveryIntent.RISK_SCORE_GENERATE_EXPORT
        )
    elif has_risk and has_generate:
        summary = orchestration_summary(
            SoftwareDeliveryIntent.RISK_SCORE_GENERATE_TESTS
        )
    elif has_risk:
        summary = orchestration_summary(SoftwareDeliveryIntent.RISK_SCORE)
    elif not outcomes:
        summary = "No software-delivery tools were invoked."
    else:
        summary = "Completed a partial software-delivery tool run."

    if truncated:
        summary = summary + _TRUNCATED_NOTE
    return summary


def _agent_goal(
    *,
    target: str,
    hits: Sequence[ScoredChunk],
    generate_tests: bool,
) -> str:
    snippets = []
    for hit in hits[:8]:
        ref = hit.chunk.reference
        payload = (
            f"[source_type={ref.source_type} source_id={ref.source_id}]\n"
            f"{hit.chunk.content[:400]}"
        )
        snippets.append(
            AGENT_BOUNDARY.wrap("evidence", payload, include_notice=True)
        )
    evidence_block = "\n".join(snippets) if snippets else "(no snippets)"
    if generate_tests:
        task = (
            "Score risk, generate test cases, and export Markdown using the "
            "bound tools. Prefer that order when dependencies require it."
        )
    else:
        task = "Score software-delivery risk using the bound risk tool."
    return (
        f"{AGENT_BOUNDARY.wrap('target', target, include_notice=True)}\n\n"
        f"Task: {task}\n\n"
        f"Evidence snippets:\n{evidence_block}"
    )
