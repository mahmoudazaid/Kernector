"""Chat-time Software Delivery tool runs: retrieve, orchestrate, project.

Turns a matched chat intent into a real tool chain and projects its typed
results onto the composition-facing ``ToolRunOutcome`` that
``ToolAugmentedAsk`` puts on an ``AskResponse``. Pack types are matched
structurally, never imported: this module is reachable from
``import composition``, which must not load a pack.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from application.citations import build_citations
from application.contracts import InvokeToolResponse
from application.errors import ApplicationValidationError, InsufficientEvidenceError
from composition.tool_augmented_ask import ToolRunOutcome
from domain.errors import DomainValidationError
from domain.knowledge import ScoredChunk

OpaqueInvoke = Callable[[str, Mapping[str, object]], str]

# Duplicated from the pack's TEST_CASE_STYLES on purpose: validating here would
# otherwise mean importing the pack at ``import composition`` time. The drift is
# pinned by test_exported_styles_match_the_pack.
SOFTWARE_DELIVERY_TEST_STYLES: tuple[str, ...] = ("steps", "gherkin")

_UNKNOWN_OUTCOME_MESSAGE = "The tool run produced an unrecognised result."
_TOOL_RUN_FAILED_MESSAGE = "A tool failed during the run."
_NO_EVIDENCE_MESSAGE = (
    "No ingested document was relevant enough to ground this tool run."
)


class ToolRunFailedError(RuntimeError):
    """A tool run could not be turned into an answer.

    The message is composition-authored and fixed; tool and vendor detail stay
    on ``__cause__``, so nothing a provider said reaches a chat bubble.

    Attributes:
        tool_outputs (tuple[InvokeToolResponse, ...]): Opaque results recorded
            before the failure, so a caller can still say what did run.
    """

    def __init__(
        self,
        message: str,
        *,
        tool_outputs: Sequence[InvokeToolResponse] = (),
    ) -> None:
        super().__init__(message)
        self.tool_outputs: tuple[InvokeToolResponse, ...] = tuple(tool_outputs)


class ToolCallRecorder:
    """Wraps opaque invoke and keeps one output per successful call.

    Recorded at the ``InvokeTool`` boundary, so nothing here interprets a pack
    payload — which is what keeps ``AskResponse.tool_outputs`` opaque.
    """

    def __init__(self, invoke: OpaqueInvoke) -> None:
        self._invoke = invoke
        self._outputs: list[InvokeToolResponse] = []

    @property
    def tool_outputs(self) -> tuple[InvokeToolResponse, ...]:
        """Opaque results of every call that returned, in invocation order."""
        return tuple(self._outputs)

    def __call__(self, tool_name: str, arguments: Mapping[str, object]) -> str:
        result = self._invoke(tool_name, arguments)
        # A raise never reaches here, and ``InvokeToolResponse`` rejects a blank
        # result — so a failed or empty call simply has no entry rather than a
        # placeholder the caller would have to interpret.
        if result:
            self._outputs.append(InvokeToolResponse(tool_name, result))
        return result


class _PackResponse(Protocol):
    summary: str
    outcomes: Sequence[object]


RetrieveHits = Callable[[str], Sequence[ScoredChunk]]
Orchestrate = Callable[..., _PackResponse]


def require_evidence(hits: Sequence[ScoredChunk]) -> tuple[ScoredChunk, ...]:
    """Return ``hits``, or refuse the run when nothing cleared the threshold.

    The guard has to fire *before* the evidence bundle is built: an empty bundle
    surfaces as the pack's ``OrchestrationValidationError("items must be
    non-empty")``, which tells a chat user nothing about what went wrong.
    """
    evidence = tuple(hits)
    if not evidence:
        raise InsufficientEvidenceError(_NO_EVIDENCE_MESSAGE)
    return evidence


def tool_run_answer(
    response: _PackResponse,
    *,
    tool_outputs: Sequence[InvokeToolResponse] = (),
) -> str:
    """Compose the reply from typed tool results, never from a second model call.

    The pack's own summary opens it; the risk step contributes its score band and
    rationale; the export step contributes the Markdown it already rendered, so
    generated cases reach the reader with their structure intact. Outcomes are
    matched structurally because ``composition`` may not import ``packs`` at
    module scope.

    Raises:
        ToolRunFailedError: An outcome shape nothing here recognises — better a
            loud failure than an answer that silently drops what a tool produced.
    """
    sections = [response.summary]
    for outcome in response.outcomes:
        assessment = getattr(outcome, "assessment", None)
        if assessment is not None:
            sections.append(
                f"**Risk {assessment.score}/100 ({assessment.level})** — "
                f"{assessment.rationale}"
            )
            continue
        if getattr(outcome, "result", None) is not None:
            # The generated cases reach the answer through the export step's
            # Markdown; re-rendering them here would be a second formatter to
            # keep in sync with `export_test_cases_markdown`.
            continue
        markdown = getattr(outcome, "markdown", None)
        if markdown is not None:
            sections.append(markdown)
            continue
        raise ToolRunFailedError(
            _UNKNOWN_OUTCOME_MESSAGE, tool_outputs=tool_outputs
        )
    return "\n\n".join(sections)


class PackSoftwareDeliveryChat:
    """Adapter from lazily-wired pack callables to one ``ToolRunOutcome``.

    Args:
        retrieve (RetrieveHits): Cross-source retrieval with the relevance
            threshold already applied in the container.
        invoke (OpaqueInvoke): The generic tool boundary, wrapped per run so the
            ledger belongs to that run alone.
        orchestrate (Orchestrate): Lazily-imported pack call that builds the
            evidence bundle and runs the chain.
    """

    def __init__(
        self,
        *,
        retrieve: RetrieveHits,
        invoke: OpaqueInvoke,
        orchestrate: Orchestrate,
    ) -> None:
        self._retrieve = retrieve
        self._invoke = invoke
        self._orchestrate = orchestrate

    def run(
        self,
        target: str,
        *,
        generate_tests: bool = True,
        output_style: str = "steps",
    ) -> ToolRunOutcome:
        """Retrieve evidence for ``target``, run the chain, project the result.

        Raises:
            ApplicationValidationError: ``output_style`` is not one the pack
                accepts — rejected before a retrieval call is spent.
            InsufficientEvidenceError: Nothing cleared the relevance threshold.
            ToolRunFailedError: A tool failed, or produced a shape nothing here
                recognises.
        """
        if output_style not in SOFTWARE_DELIVERY_TEST_STYLES:
            raise ApplicationValidationError(
                "output_style must be one of "
                f"{sorted(SOFTWARE_DELIVERY_TEST_STYLES)}"
            )
        hits = require_evidence(self._retrieve(target))
        recorder = ToolCallRecorder(self._invoke)
        try:
            response = self._orchestrate(
                target=target,
                hits=hits,
                generate_tests=generate_tests,
                output_style=output_style,
                invoke=recorder,
            )
        except (DomainValidationError, RuntimeError) as error:
            raise ToolRunFailedError(
                _TOOL_RUN_FAILED_MESSAGE, tool_outputs=recorder.tool_outputs
            ) from error
        # Citations come from the raw hits, not from the bundle orchestration
        # builds: that merges chunks by (source_type, source_id) and loses
        # chunk_index, so row-level provenance only survives out here.
        return ToolRunOutcome(
            answer=tool_run_answer(response, tool_outputs=recorder.tool_outputs),
            citations=build_citations(hits),
            tool_outputs=recorder.tool_outputs,
        )
