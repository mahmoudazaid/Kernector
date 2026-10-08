"""Chat-time Software Delivery tool runs: retrieve, orchestrate, project.

Turns a matched chat intent into a real tool chain and projects its typed
results onto the composition-facing ``ToolRunOutcome`` that
``ToolAugmentedAsk`` puts on an ``AskResponse``. Pack types are matched
structurally, never imported: this module is reachable from
``import composition``, which must not load a pack.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Protocol

from application.citations import build_citations
from application.contracts import Citation, InvokeToolResponse, RunMeta
from application.errors import (
    ApplicationValidationError,
    ConfigurationError,
    InsufficientEvidenceError,
)
from application.retrieval_citation_channel import RetrievalCitationChannel
from composition.software_delivery.tools import SoftwareDeliveryRunView
from composition.chat.tool_augmented_ask import ToolRunOutcome
from composition.tools.runs import ToolCallView
from composition.xray_export.receipt import xray_receipt_summary
from domain.errors import DomainValidationError
from domain.knowledge import ScoredChunk

OpaqueInvoke = Callable[[str, Mapping[str, object]], str]


class ModelCallRecorder(Protocol):
    """Per-run lifecycle for safe model-call metadata on tool turns."""

    def clear(self) -> None:
        """Discard any leftover recording from a prior run."""
        ...

    def consume(self) -> RunMeta | None:
        """Return and clear metadata recorded during the current run."""
        ...

# Duplicated from the pack's TEST_CASE_STYLES on purpose: validating here would
# otherwise mean importing the pack at ``import composition`` time. The drift is
# pinned by test_exported_styles_match_the_pack.
SOFTWARE_DELIVERY_TEST_STYLES: tuple[str, ...] = ("steps", "gherkin")

# Tool name duplicated from the pack so projection can author ToolCallView
# entries without importing packs at module scope.
_DRIVE_EXPORT_TOOL = "software_delivery.export_test_cases_google_drive"
_XRAY_TOOL = "software_delivery.create_xray_tests"

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
    @property
    def summary(self) -> str: ...

    @property
    def outcomes(self) -> Sequence[object]: ...


RetrieveHits = Callable[[str], Sequence[ScoredChunk]]
Orchestrate = Callable[..., _PackResponse]


def require_evidence(
    hits: Sequence[ScoredChunk],
    *,
    allow_empty: bool = False,
) -> tuple[ScoredChunk, ...]:
    """Return ``hits``, or refuse the run when nothing cleared the threshold.

    The guard has to fire *before* the evidence bundle is built: an empty bundle
    surfaces as the pack's ``OrchestrationValidationError("items must be
    non-empty")``, which tells a chat user nothing about what went wrong.

    Args:
        hits: Retrieval results already filtered by relevance.
        allow_empty: When True (draft-based agent export), empty hits are OK.
    """
    evidence = tuple(hits)
    if not evidence and not allow_empty:
        raise InsufficientEvidenceError(_NO_EVIDENCE_MESSAGE)
    return evidence


def tool_run_answer(
    response: _PackResponse,
    *,
    tool_outputs: Sequence[InvokeToolResponse] = (),
) -> str:
    """Compose the reply from typed tool results, never from a second model call.

    The orchestrate summary opens it; a Drive export receipt contributes the
    exported file name. Outcomes are matched structurally because
    ``composition`` may not import ``packs`` at module scope.

    Raises:
        ToolRunFailedError: An outcome shape nothing here recognises — better a
            loud failure than an answer that silently drops what a tool produced.
    """
    sections = [response.summary]
    for outcome in response.outcomes:
        if getattr(outcome, "outcome", None) == "export_destination_required":
            continue
        xray_summary = _xray_summary(outcome)
        if xray_summary is not None:
            sections.append(xray_summary)
            continue
        file_id = getattr(outcome, "file_id", None)
        file_name = getattr(outcome, "file_name", None)
        if file_id is not None or file_name is not None:
            name = file_name if isinstance(file_name, str) and file_name else "file"
            sections.append(f"Exported **{name}** to Google Drive.")
            continue
        raise ToolRunFailedError(
            _UNKNOWN_OUTCOME_MESSAGE, tool_outputs=tool_outputs
        )
    return "\n\n".join(sections)


def _xray_summary(outcome: object) -> str | None:
    keys = getattr(outcome, "created_keys", None)
    if not isinstance(keys, tuple):
        return None
    failed = getattr(outcome, "failed_count", 0)
    project_key = getattr(outcome, "project_key", None)
    return xray_receipt_summary(
        tuple(key for key in keys if isinstance(key, str)),
        failed if isinstance(failed, int) and not isinstance(failed, bool) else 0,
        project_key if isinstance(project_key, str) else None,
    )


def project_software_delivery_run_view(
    response: _PackResponse,
    *,
    tool_outputs: Sequence[InvokeToolResponse] = (),
) -> SoftwareDeliveryRunView:
    """Project typed pack outcomes onto presentation views.

    Summaries are authored from validated typed metadata, never from opaque
    ``InvokeToolResponse.result`` strings. Outcomes are matched structurally
    because ``composition`` may not import ``packs``.

    Raises:
        ToolRunFailedError: An outcome shape nothing here recognises.
    """
    calls: list[ToolCallView] = []
    export_destination_required = False
    drive_file_id = ""
    drive_file_name = ""
    drive_destination_label = ""

    for outcome in response.outcomes:
        if getattr(outcome, "outcome", None) == "export_destination_required":
            export_destination_required = True
            continue

        xray_summary = _xray_summary(outcome)
        if xray_summary is not None:
            calls.append(ToolCallView(_XRAY_TOOL, ok=True, summary=xray_summary))
            continue

        file_id = getattr(outcome, "file_id", None)
        file_name = getattr(outcome, "file_name", None)
        if file_id is not None or file_name is not None:
            drive_file_id = file_id if isinstance(file_id, str) else ""
            drive_file_name = file_name if isinstance(file_name, str) else ""
            label = getattr(outcome, "destination_label", "")
            drive_destination_label = label if isinstance(label, str) else ""
            calls.append(
                ToolCallView(
                    _DRIVE_EXPORT_TOOL,
                    ok=True,
                    summary="Exported test cases to Google Drive",
                )
            )
            continue

        raise ToolRunFailedError(
            _UNKNOWN_OUTCOME_MESSAGE, tool_outputs=tool_outputs
        )

    return SoftwareDeliveryRunView(
        summary=response.summary,
        calls=tuple(calls),
        export_destination_required=export_destination_required,
        drive_file_id=drive_file_id,
        drive_file_name=drive_file_name,
        drive_destination_label=drive_destination_label,
        pending_approval=getattr(response, "pending_approval", None),
    )


class PackSoftwareDeliveryChat:
    """Adapter from lazily-wired pack callables to one ``ToolRunOutcome``.

    Args:
        retrieve (RetrieveHits): Cross-source retrieval with the relevance
            threshold already applied in the container.
        invoke (OpaqueInvoke): The generic tool boundary, wrapped per run so the
            ledger belongs to that run alone.
        orchestrate (Orchestrate): Lazily-imported pack call that builds the
            evidence bundle and runs the chain.
        model_calls (ModelCallRecorder | None): Shared recorder for ChatModel
            calls made inside tools (e.g. test generation). Cleared at run
            start and on every exit; consumed metadata is merged into
            ``ToolRunOutcome.run`` with retrieval/citation counts.
        allow_empty_evidence (bool): When True (agent export path), empty
            retrieval hits are OK. Must not be derived from conversation_id —
            the web client always sends one.
        defer_retrieval (bool): When True (agent loop), skip pre-orchestrate
            retrieve; the agent may call a retrieve tool mid-run instead.
        citation_channel (RetrievalCitationChannel | None): When set with
            ``defer_retrieval``, citations come from this side channel after
            the agent turn — not from pre-orchestrate hits.
    """

    def __init__(
        self,
        *,
        retrieve: RetrieveHits,
        invoke: OpaqueInvoke,
        orchestrate: Orchestrate,
        model_calls: ModelCallRecorder | None = None,
        allow_empty_evidence: bool = False,
        defer_retrieval: bool = False,
        citation_channel: RetrievalCitationChannel | None = None,
    ) -> None:
        self._retrieve = retrieve
        self._invoke = invoke
        self._orchestrate = orchestrate
        self._model_calls = model_calls
        self._allow_empty_evidence = allow_empty_evidence
        self._defer_retrieval = defer_retrieval
        self._citation_channel = citation_channel

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
        if self._model_calls is not None:
            self._model_calls.clear()
        try:
            if self._citation_channel is not None:
                self._citation_channel.clear()
            if self._defer_retrieval:
                hits: Sequence[ScoredChunk] = ()
            elif need_evidence:
                hits = require_evidence(
                    self._retrieve(target),
                    allow_empty=self._allow_empty_evidence,
                )
            elif self._allow_empty_evidence:
                # Drive-export ready path: titles come from the draft, not RAG.
                hits = ()
            else:
                hits = require_evidence(
                    self._retrieve(target),
                    allow_empty=False,
                )
            recorder = ToolCallRecorder(self._invoke)
            try:
                response = self._orchestrate(
                    target=target,
                    hits=hits,
                    generate_tests=generate_tests,
                    output_style=output_style,
                    invoke=recorder,
                    conversation_id=conversation_id,
                    response_style=response_style,
                )
            except ConfigurationError:
                raise
            except (DomainValidationError, RuntimeError) as error:
                raise ToolRunFailedError(
                    _TOOL_RUN_FAILED_MESSAGE, tool_outputs=recorder.tool_outputs
                ) from error
            # Citations: deferred agent path uses the typed side channel.
            # Pre-orchestrate path uses raw hits (bundle merges lose chunk_index).
            if self._defer_retrieval and self._citation_channel is not None:
                citations = self._citation_channel.drain()
            else:
                citations = build_citations(hits)
            model_meta = (
                None if self._model_calls is None else self._model_calls.consume()
            )
            answer = tool_run_answer(
                response, tool_outputs=recorder.tool_outputs
            )
            run_view = project_software_delivery_run_view(
                response, tool_outputs=recorder.tool_outputs
            )
            return ToolRunOutcome(
                answer=answer,
                citations=citations,
                tool_outputs=recorder.tool_outputs,
                run=_run_meta_for_tool_outcome(
                    model_meta,
                    hits=hits,
                    citations=citations,
                ),
                run_view=run_view,
                pending_approval=getattr(response, "pending_approval", None),
            )
        finally:
            if self._model_calls is not None:
                self._model_calls.clear()


def _run_meta_for_tool_outcome(
    model_meta: RunMeta | None,
    *,
    hits: Sequence[ScoredChunk],
    citations: Sequence[Citation],
) -> RunMeta:
    """Attach retrieval/citation counts; preserve any model latency/tokens."""
    base = model_meta if model_meta is not None else RunMeta()
    return replace(
        base,
        # Deferred agent retrieval leaves ``hits`` empty; cite channel size.
        hit_count=len(hits) if hits else len(citations),
        citation_count=len(citations),
    )
