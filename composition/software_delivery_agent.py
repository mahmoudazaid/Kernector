"""Agent-backed Software Delivery orchestrate for chat-time tool runs.

When ``SOFTWARE_DELIVERY_AGENT_LOOP`` is on, composition injects this orchestrate
in place of the deterministic #170 chain. Pack imports stay lazy so
``import composition`` never loads a pack.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from application.run_tool_agent import RunToolAgent
from composition.software_delivery_chat import OpaqueInvoke, Orchestrate
from domain.knowledge import ScoredChunk
from domain.ports import Tool, ToolCallingAgent

_RISK_TOOL = "software_delivery.risk_score"
_GENERATE_TOOL = "software_delivery.generate_test_cases"
_EXPORT_TOOL = "software_delivery.export_test_cases_markdown"

_DEFAULT_MAX_STEPS = 8


@dataclass(frozen=True, slots=True)
class _PackResponse:
    summary: str
    outcomes: tuple[object, ...]


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
        del arguments  # Agent may omit args; evidence is closed over.
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
        agent (ToolCallingAgent): Injected agent port (fake or LangGraph adapter).
        max_steps (int): Hard stop forwarded to ``RunToolAgent``.

    Returns:
        Orchestrate: Compatible with ``PackSoftwareDeliveryChat``.
    """
    run_agent = RunToolAgent(agent)

    def orchestrate(
        *,
        target: str,
        hits: Sequence[ScoredChunk],
        generate_tests: bool,
        output_style: str,
        invoke: OpaqueInvoke,
    ) -> _PackResponse:
        from packs.software_delivery.evidence_bundle import (
            evidence_bundle_from_hits,
            export_tool_arguments,
            generate_test_tool_arguments,
            risk_tool_arguments,
        )
        from packs.software_delivery.orchestration_contracts import (
            ExportMarkdownOutcome,
            GenerateTestsOutcome,
            RiskScoreOutcome,
        )
        from packs.software_delivery.orchestration_policy import (
            SoftwareDeliveryIntent,
            orchestration_summary,
        )
        from packs.software_delivery.tool_results import (
            parse_risk_assessment_result,
            parse_test_generation_result,
            serialize_test_generation_for_export,
        )

        evidence = evidence_bundle_from_hits(hits)
        outcomes: list[object] = []
        generation_raw: list[str] = []

        def on_risk(raw: str) -> None:
            outcomes.append(RiskScoreOutcome(parse_risk_assessment_result(raw)))

        def on_generate(raw: str) -> None:
            generation_raw.append(raw)
            outcomes.append(
                GenerateTestsOutcome(parse_test_generation_result(raw))
            )

        def on_export(raw: str) -> None:
            outcomes.append(ExportMarkdownOutcome(raw))

        tools: list[Tool] = [
            _BoundTool(
                _RISK_TOOL,
                "Score software-delivery risk from the evidence bundle.",
                invoke,
                risk_tool_arguments(target, evidence),
                on_risk,
            )
        ]
        if generate_tests:
            tools.append(
                _BoundTool(
                    _GENERATE_TOOL,
                    "Generate test cases from the evidence bundle.",
                    invoke,
                    generate_test_tool_arguments(target, evidence, output_style),
                    on_generate,
                )
            )

            def export_args() -> Mapping[str, object]:
                if not generation_raw:
                    from domain.errors import ToolFailureError

                    raise ToolFailureError(
                        "Generate test cases outcome required before Markdown export"
                    )
                parsed = parse_test_generation_result(generation_raw[-1])
                return export_tool_arguments(
                    serialize_test_generation_for_export(parsed)
                )

            # Export args depend on a prior generate call; resolve lazily.
            tools.append(
                _LazyExportTool(
                    invoke=invoke,
                    arguments_factory=export_args,
                    on_result=on_export,
                )
            )

        goal = _agent_goal(target=target, hits=hits, generate_tests=generate_tests)
        run_agent.execute(goal, tools, max_steps=max_steps)

        intent = (
            SoftwareDeliveryIntent.RISK_SCORE_GENERATE_EXPORT
            if generate_tests
            else SoftwareDeliveryIntent.RISK_SCORE
        )
        return _PackResponse(
            summary=orchestration_summary(intent),
            outcomes=tuple(outcomes),
        )

    return orchestrate


@dataclass(frozen=True, slots=True)
class _LazyExportTool:
    """Export tool that builds arguments after generate has run."""

    invoke: OpaqueInvoke
    arguments_factory: object  # Callable[[], Mapping[str, object]]
    on_result: object  # Callable[[str], None]
    _name: str = _EXPORT_TOOL
    _description: str = "Export generated test cases as Markdown."

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def run(self, arguments: Mapping[str, object]) -> str:
        del arguments
        args = self.arguments_factory()  # type: ignore[operator]
        result = self.invoke(self._name, args)
        self.on_result(result)  # type: ignore[operator]
        return result


def _agent_goal(
    *,
    target: str,
    hits: Sequence[ScoredChunk],
    generate_tests: bool,
) -> str:
    snippets = []
    for hit in hits[:8]:
        ref = hit.chunk.reference
        snippets.append(
            f"- [{ref.source_type}:{ref.source_id}] {hit.chunk.content[:400]}"
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
        f"Target: {target}\n\n"
        f"Task: {task}\n\n"
        f"Evidence snippets:\n{evidence_block}"
    )
