"""Orchestrate Software Delivery tools from a retrieved evidence bundle."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from application.citations import build_citations
from application.contracts import (
    InvokeToolRequest,
    InvokeToolResponse,
    OrchestrateSoftwareDeliveryRequest,
    OrchestrateSoftwareDeliveryResponse,
    RetrieveRequest,
    SoftwareDeliveryIntent,
)
from application.errors import ApplicationValidationError
from application.grounded_rag_policy import INSUFFICIENT_KNOWLEDGE_ANSWER
from application.input_safety import reject_unsafe_query
from application.invoke_tool import InvokeTool
from application.rewrite_and_retrieve import RewriteAndRetrieveKnowledge
from application.tool_evidence import base_tool_arguments
from domain.errors import ToolFailureError
from domain.knowledge import ScoredChunk

RISK_SCORE = "software_delivery.risk_score"
GENERATE_TEST_CASES = "software_delivery.generate_test_cases"
EXPORT_TEST_CASES_MARKDOWN = "software_delivery.export_test_cases_markdown"

_ANSWER_BY_INTENT = {
    SoftwareDeliveryIntent.RISK_SCORE: (
        "Scored software-delivery risk from retrieved evidence."
    ),
    SoftwareDeliveryIntent.GENERATE_TESTS: (
        "Generated test cases from retrieved evidence."
    ),
    SoftwareDeliveryIntent.GENERATE_AND_EXPORT: (
        "Generated test cases and exported Markdown from retrieved evidence."
    ),
}


class OrchestrateSoftwareDelivery:
    """Retrieve evidence, then select and chain Software Delivery tools.

    Intent selection and multi-tool chaining live here. Generic ``InvokeTool``
    remains opaque: this use case builds plain dict arguments and only
    ``json.loads`` tool string results when chaining generate → export.

    Args:
        rewrite_and_retrieve (RewriteAndRetrieveKnowledge): Retrieval use case.
        invoke_tool (InvokeTool): Opaque single-tool invocation.
        default_retrieval_limit (int): Limit when the request omits one.
        relevance_threshold (float): Minimum score for a hit to count as evidence.
        max_input_length (int): Character cap for ``query`` and ``target``.
    """

    def __init__(
        self,
        rewrite_and_retrieve: RewriteAndRetrieveKnowledge,
        invoke_tool: InvokeTool,
        *,
        default_retrieval_limit: int,
        relevance_threshold: float,
        max_input_length: int,
    ) -> None:
        self._rewrite_and_retrieve = rewrite_and_retrieve
        self._invoke_tool = invoke_tool
        self._default_retrieval_limit = default_retrieval_limit
        self._relevance_threshold = relevance_threshold
        self._max_input_length = max_input_length

    def execute(
        self, request: OrchestrateSoftwareDeliveryRequest
    ) -> OrchestrateSoftwareDeliveryResponse:
        """Retrieve relevant evidence and run the requested tool intent.

        Args:
            request (OrchestrateSoftwareDeliveryRequest): Intent, target, query.

        Returns:
            OrchestrateSoftwareDeliveryResponse: Citations, tool outputs, summary.

        Raises:
            ApplicationValidationError: Oversized inputs or unsafe query text.
            ToolArgumentValidationError: Propagated from a tool.
            ToolFailureError: Propagated from a tool, or invalid generate JSON
                when chaining to export.
            ProviderError: Rewrite, embedding, or chat provider failed.
            VectorStoreError: Vector-store search failed.
        """
        self._guard_lengths(request)
        reject_unsafe_query(request.query)
        limit = request.retrieval_limit or self._default_retrieval_limit
        retrieved = self._rewrite_and_retrieve.execute(
            RetrieveRequest(query=request.query, retrieval_limit=limit)
        )
        hits = self._relevant(retrieved.hits)
        if not hits:
            return OrchestrateSoftwareDeliveryResponse(
                answer=INSUFFICIENT_KNOWLEDGE_ANSWER
            )

        outputs = self._run_intent(request, hits)
        return OrchestrateSoftwareDeliveryResponse(
            answer=_ANSWER_BY_INTENT[request.intent],
            citations=build_citations(hits),
            tool_outputs=outputs,
        )

    def _guard_lengths(self, request: OrchestrateSoftwareDeliveryRequest) -> None:
        for field_name, value in (
            ("query", request.query),
            ("target", request.target),
        ):
            if len(value) > self._max_input_length:
                raise ApplicationValidationError(
                    f"{field_name} must be at most {self._max_input_length} "
                    f"characters, got {len(value)}"
                )

    def _relevant(self, hits: Sequence[ScoredChunk]) -> tuple[ScoredChunk, ...]:
        return tuple(hit for hit in hits if hit.score >= self._relevance_threshold)

    def _run_intent(
        self,
        request: OrchestrateSoftwareDeliveryRequest,
        hits: Sequence[ScoredChunk],
    ) -> tuple[InvokeToolResponse, ...]:
        base = base_tool_arguments(request.target, hits)
        if request.intent is SoftwareDeliveryIntent.RISK_SCORE:
            return (self._invoke(RISK_SCORE, base),)

        generate_args: dict[str, object] = {
            **base,
            "output_style": request.output_style,
        }
        generated = self._invoke(GENERATE_TEST_CASES, generate_args)
        if request.intent is SoftwareDeliveryIntent.GENERATE_TESTS:
            return (generated,)

        export_args = _export_arguments_from_generate_result(generated.result)
        exported = self._invoke(EXPORT_TEST_CASES_MARKDOWN, export_args)
        return (generated, exported)

    def _invoke(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> InvokeToolResponse:
        return self._invoke_tool.execute(InvokeToolRequest(tool_name, arguments))


def _export_arguments_from_generate_result(result: str) -> dict[str, object]:
    """Parse generate JSON into opaque export arguments.

    Raises:
        ToolFailureError: Result is not a mapping with export fields.
    """
    try:
        payload = json.loads(result)
    except json.JSONDecodeError as exc:
        raise ToolFailureError(
            "Generate test cases result was not valid JSON for export"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ToolFailureError(
            "Generate test cases result must be a JSON object for export"
        )
    if "output_style" not in payload or "test_cases" not in payload:
        raise ToolFailureError(
            "Generate test cases result missing output_style or test_cases"
        )
    return {
        "output_style": payload["output_style"],
        "test_cases": payload["test_cases"],
    }
