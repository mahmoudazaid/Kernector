"""Tool-run presentation logic for the Streamlit layer.

Owns the call into the composition tool runner, the generic tool-call envelope
formatting, the pack-specific result formatting, and the mapping of typed
failures to fixed, user-safe sentences. Widgets and ``st`` calls stay in
``tool_run_panel.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from application.errors import ApplicationValidationError, InsufficientEvidenceError
from composition import (
    RiskFactorView,
    SoftwareDeliveryRunView,
    SoftwareDeliveryToolRunner,
    TestCaseView,
    ToolCallView,
    ToolRunFailedError,
)
from domain.errors import DomainValidationError, ProviderError
from domain.knowledge import SourceReference

logger = logging.getLogger(__name__)

_BLANK_TARGET_MESSAGE = "Describe what to assess before running the tools."
_TOOL_FAILURE_MESSAGE = (
    "A tool failed during the run. The calls below show where it stopped."
)
_PROVIDER_FAILURE_MESSAGE = "The model provider could not complete the tool run."
_INSUFFICIENT_EVIDENCE_MESSAGE = (
    "No ingested document was relevant enough to ground this tool run."
)
_OPERATIONAL_FAILURE_MESSAGE = "Something went wrong while running the tools."
_UNEXPECTED_FAILURE_MESSAGE = "The tool run failed unexpectedly. Check the server logs."


@dataclass(frozen=True, slots=True)
class ToolTurnResult:
    """UI-neutral outcome of one tool-run submission.

    Attributes:
        ok (bool): Whether the run produced a view.
        message (str): User-facing error text when ``ok`` is false.
        view (SoftwareDeliveryRunView | None): Structured results on success.
        calls (tuple[ToolCallView, ...]): Generic envelope for every tool that
            ran, present on success *and* on a tool failure.
    """

    ok: bool
    message: str = ""
    view: SoftwareDeliveryRunView | None = None
    calls: tuple[ToolCallView, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolRunContext:
    """Live UI inputs that ground one tool-run submission.

    Attributes:
        target (str): What the tools were asked to assess.
        generate_tests (bool): Whether the chain generated and exported cases.
        output_style (str): Requested test-case style.
        provider (str): Selected model provider.
        model (str): Selected model.
    """

    target: str
    generate_tests: bool
    output_style: str
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class StoredToolRunResult:
    """A run outcome bound to the inputs and model that produced it."""

    context: ToolRunContext
    result: ToolTurnResult


def _validation_message(error: BaseException) -> str:
    """Validation messages are authored at the application boundary."""
    text = str(error).strip()
    return text or f"The request failed ({type(error).__name__})."


def _references(references: Sequence[SourceReference]) -> str:
    return ", ".join(f"`{ref.source_id}` ({ref.source_type})" for ref in references)


def tool_call_lines(calls: Sequence[ToolCallView]) -> tuple[str, ...]:
    """Render the generic envelope: what ran, whether it worked, how much came back.

    The payload is measured, never parsed — interpreting it here would put pack
    knowledge into the one part of this feature that is meant to be generic.
    """
    return tuple(
        f"- `{call.tool_name}` — succeeded · {len(call.result)} characters"
        if call.ok
        else f"- `{call.tool_name}` — failed"
        for call in calls
    )


def risk_factor_bullets(
    factors: Sequence[RiskFactorView],
) -> tuple[str, ...]:
    """Render risk factors as Markdown bullets, each carrying its provenance."""
    return tuple(
        f"- `{factor.factor_id}` (weight {factor.weight}) — "
        + _references(factor.references)
        for factor in factors
    )


def case_lines(case: TestCaseView) -> tuple[str, ...]:
    """Render one generated case: numbered steps, expectation, provenance."""
    return (
        *(f"{index}. {step}" for index, step in enumerate(case.steps, start=1)),
        "",
        f"**Expected:** {case.expected}",
        f"**References:** {_references(case.references)}",
    )


def run_tool_turn(
    runner: SoftwareDeliveryToolRunner,
    *,
    target: str,
    generate_tests: bool = True,
    output_style: str = "steps",
) -> ToolTurnResult:
    """Run the tool chain and classify the outcome."""
    if not target.strip():
        return ToolTurnResult(ok=False, message=_BLANK_TARGET_MESSAGE)

    try:
        view = runner.run(
            target, generate_tests=generate_tests, output_style=output_style
        )
    except ApplicationValidationError as error:
        return ToolTurnResult(ok=False, message=_validation_message(error))
    except ToolRunFailedError as error:
        return ToolTurnResult(
            ok=False, message=_TOOL_FAILURE_MESSAGE, calls=error.calls
        )
    except ProviderError:
        return ToolTurnResult(ok=False, message=_PROVIDER_FAILURE_MESSAGE)
    except InsufficientEvidenceError:
        return ToolTurnResult(ok=False, message=_INSUFFICIENT_EVIDENCE_MESSAGE)
    except (DomainValidationError, RuntimeError):
        return ToolTurnResult(ok=False, message=_OPERATIONAL_FAILURE_MESSAGE)
    except Exception:
        logger.exception("Unexpected failure during the tool run")
        return ToolTurnResult(ok=False, message=_UNEXPECTED_FAILURE_MESSAGE)
    return ToolTurnResult(ok=True, view=view, calls=view.calls)


def tool_run_result_for_display(
    stored: StoredToolRunResult | None,
    *,
    context: ToolRunContext,
) -> ToolTurnResult | None:
    """Return a stored outcome only when it still matches the live UI context."""
    if stored is None or stored.context != context:
        return None
    return stored.result


def tool_run_result_after_successful_document_mutation(
    stored: StoredToolRunResult | None,
) -> StoredToolRunResult | None:
    """Successful corpus mutations invalidate any stored grounded run."""
    return None
