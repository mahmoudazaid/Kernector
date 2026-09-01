"""Requirements-analysis presentation logic for the Streamlit layer.

Owns the call into the composition analyzer facade, the citation projection,
finding formatting, stored-result context matching, and the mapping of typed
failures to fixed, user-safe sentences. Widgets and ``st`` calls stay in
``app.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from application.contracts import Citation
from application.errors import ApplicationValidationError, InsufficientEvidenceError
from composition import (
    RequirementsAnalysisFindingView,
    RequirementsAnalysisView,
    RequirementsAnalyzer,
    analysis_citations,
)
from domain.errors import DomainValidationError, ProviderError

logger = logging.getLogger(__name__)

_BLANK_REQUIREMENTS_MESSAGE = "Paste requirements before running the analysis."
_PROVIDER_FAILURE_MESSAGE = "The model provider could not complete the analysis."
_INSUFFICIENT_EVIDENCE_MESSAGE = (
    "No ingested document was relevant enough to ground this analysis."
)
_OPERATIONAL_FAILURE_MESSAGE = "Something went wrong while analyzing the requirements."
_UNEXPECTED_FAILURE_MESSAGE = "Analysis failed unexpectedly. Check the server logs."


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    """Live UI inputs that ground one requirements-analysis submission."""

    requirements: str
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class AnalysisTurnResult:
    """UI-neutral outcome of one requirements-analysis submission.

    Attributes:
        ok (bool): Whether the analysis returned a view.
        message (str): User-facing error text when ``ok`` is false.
        view (RequirementsAnalysisView | None): Structured findings on success.
        citations (tuple[Citation, ...]): Generic provenance for the evidence
            behind ``view``, projected at the composition edge.
    """

    ok: bool
    message: str = ""
    view: RequirementsAnalysisView | None = None
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class StoredAnalysisResult:
    """A turn outcome bound to the requirements and model that produced it."""

    context: AnalysisContext
    result: AnalysisTurnResult


def _validation_message(error: BaseException) -> str:
    """Validation messages are authored at the application boundary."""
    text = str(error).strip()
    return text or f"The request failed ({type(error).__name__})."


def run_analysis_turn(
    analyzer: RequirementsAnalyzer,
    *,
    requirements: str,
) -> AnalysisTurnResult:
    """Run requirements analysis and classify the outcome."""
    if not requirements.strip():
        return AnalysisTurnResult(ok=False, message=_BLANK_REQUIREMENTS_MESSAGE)

    try:
        view = analyzer.analyze(requirements)
    except ApplicationValidationError as error:
        return AnalysisTurnResult(ok=False, message=_validation_message(error))
    except ProviderError:
        return AnalysisTurnResult(ok=False, message=_PROVIDER_FAILURE_MESSAGE)
    except InsufficientEvidenceError:
        return AnalysisTurnResult(ok=False, message=_INSUFFICIENT_EVIDENCE_MESSAGE)
    except (DomainValidationError, RuntimeError):
        return AnalysisTurnResult(ok=False, message=_OPERATIONAL_FAILURE_MESSAGE)
    except Exception:
        logger.exception("Unexpected failure during requirements analysis")
        return AnalysisTurnResult(ok=False, message=_UNEXPECTED_FAILURE_MESSAGE)
    return AnalysisTurnResult(ok=True, view=view, citations=analysis_citations(view))


def analysis_result_for_display(
    stored: StoredAnalysisResult | None,
    *,
    context: AnalysisContext,
) -> AnalysisTurnResult | None:
    """Return a stored outcome only when it still matches the live UI context."""
    if stored is None or stored.context != context:
        return None
    return stored.result


def analysis_result_after_successful_document_mutation(
    stored: StoredAnalysisResult | None,
) -> StoredAnalysisResult | None:
    """Successful corpus mutations invalidate any stored grounded analysis."""
    return None


def finding_bullets(
    findings: Sequence[RequirementsAnalysisFindingView],
) -> tuple[str, ...]:
    """Render findings as Markdown bullets, each carrying its provenance."""
    return tuple(
        f"- {finding.statement} — "
        + ", ".join(
            f"`{ref.source_id}` ({ref.source_type})" for ref in finding.references
        )
        for finding in findings
    )
