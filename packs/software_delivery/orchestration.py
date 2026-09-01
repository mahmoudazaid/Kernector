"""Chain Software Delivery tools over a retrieved evidence bundle."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from domain.errors import ToolFailureError
from packs.software_delivery.evidence_bundle import (
    export_tool_arguments,
    risk_tool_arguments,
    generate_test_tool_arguments,
)
from packs.software_delivery.orchestration_contracts import (
    ExportMarkdownOutcome,
    GenerateTestsOutcome,
    OrchestrateSoftwareDeliveryRequest,
    OrchestrateSoftwareDeliveryResponse,
    RiskScoreOutcome,
    SoftwareDeliveryOutcome,
)
from packs.software_delivery.orchestration_policy import (
    EXPORT_TEST_CASES_MARKDOWN_TOOL,
    GENERATE_TEST_CASES_TOOL,
    RISK_SCORE_TOOL,
    orchestration_summary,
    tool_chain,
)
from packs.software_delivery.tool_results import (
    parse_risk_assessment_result,
    parse_test_generation_result,
    serialize_test_generation_for_export,
)

OpaqueInvoke = Callable[[str, Mapping[str, object]], str]


class OrchestrateSoftwareDelivery:
    """Select and run ordered Software Delivery tool chains via opaque invoke.

    Consumes an already-retrieved ``EvidenceBundle``; retrieval and query
    rewriting stay outside this use case. Generic tool invocation treats
    arguments and string results as opaque at the boundary; this class
    deserializes results into pack-local typed outcomes before returning.

    Args:
        invoke (OpaqueInvoke): Callable that runs one tool by name and returns
            its opaque string result.
    """

    def __init__(self, invoke: OpaqueInvoke) -> None:
        self._invoke = invoke

    def execute(
        self, request: OrchestrateSoftwareDeliveryRequest
    ) -> OrchestrateSoftwareDeliveryResponse:
        """Run the tool chain for ``request.intent`` with failure short-circuit.

        Args:
            request (OrchestrateSoftwareDeliveryRequest): Intent, target, and
                evidence bundle.

        Returns:
            OrchestrateSoftwareDeliveryResponse: Summary and typed step outcomes.

        Raises:
            OrchestrationValidationError: Invalid request fields.
            ToolArgumentValidationError: Propagated from a tool.
            ToolFailureError: Propagated from a tool or invalid tool JSON.
        """
        outcomes: list[SoftwareDeliveryOutcome] = []
        for tool_name in tool_chain(request.intent):
            if tool_name == RISK_SCORE_TOOL:
                raw = self._invoke(
                    tool_name,
                    risk_tool_arguments(request.target, request.evidence),
                )
                outcomes.append(
                    RiskScoreOutcome(parse_risk_assessment_result(raw))
                )
                continue
            if tool_name == GENERATE_TEST_CASES_TOOL:
                raw = self._invoke(
                    tool_name,
                    generate_test_tool_arguments(
                        request.target,
                        request.evidence,
                        request.output_style,
                    ),
                )
                outcomes.append(
                    GenerateTestsOutcome(parse_test_generation_result(raw))
                )
                continue
            if tool_name == EXPORT_TEST_CASES_MARKDOWN_TOOL:
                generated = _latest_generation(outcomes)
                export_payload = serialize_test_generation_for_export(
                    generated.result
                )
                raw = self._invoke(
                    tool_name,
                    export_tool_arguments(export_payload),
                )
                outcomes.append(ExportMarkdownOutcome(raw))
                continue
            raise ToolFailureError(f"unknown orchestration tool: {tool_name!r}")

        return OrchestrateSoftwareDeliveryResponse(
            summary=orchestration_summary(request.intent),
            outcomes=tuple(outcomes),
        )


def _latest_generation(
    outcomes: list[SoftwareDeliveryOutcome],
) -> GenerateTestsOutcome:
    for outcome in reversed(outcomes):
        if isinstance(outcome, GenerateTestsOutcome):
            return outcome
    raise ToolFailureError(
        "Generate test cases outcome required before Markdown export"
    )
