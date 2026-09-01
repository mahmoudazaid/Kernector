"""Requirements-analysis presentation logic for the Streamlit layer.

Owns the call into the composition analyzer facade, the citation projection,
finding formatting, pack availability, and the mapping of typed failures to
fixed, user-safe sentences. Widgets and ``st`` calls stay in ``app.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from application.contracts import Citation
from application.errors import ApplicationValidationError
from composition import (
    RequirementsAnalysisFindingView,
    RequirementsAnalysisView,
    RequirementsAnalyzer,
    RequirementsEvidenceUnavailableError,
    Settings,
    analysis_citations,
)
from domain.errors import DomainValidationError, ProviderError

logger = logging.getLogger(__name__)

_BLANK_REQUIREMENTS_MESSAGE = "Paste requirements before running the analysis."
_PROVIDER_FAILURE_MESSAGE = "The model provider could not complete the analysis."
_OPERATIONAL_FAILURE_MESSAGE = "Something went wrong while analyzing the requirements."
_UNEXPECTED_FAILURE_MESSAGE = "Analysis failed unexpectedly. Check the server logs."

_ANALYSIS_PACK_ID = "software-delivery"


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
    except RequirementsEvidenceUnavailableError as error:
        return AnalysisTurnResult(ok=False, message=str(error))
    except (DomainValidationError, RuntimeError):
        return AnalysisTurnResult(ok=False, message=_OPERATIONAL_FAILURE_MESSAGE)
    except Exception:
        logger.exception("Unexpected failure during requirements analysis")
        return AnalysisTurnResult(ok=False, message=_UNEXPECTED_FAILURE_MESSAGE)
    return AnalysisTurnResult(ok=True, view=view, citations=analysis_citations(view))


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


def analysis_enabled(settings: Settings) -> bool:
    """Whether the domain pack behind requirements analysis is enabled.

    Presentation names the pack *id* — a configuration value read out of
    settings, not an import. ``LAYER_RULES["presentation"]`` bans importing
    ``packs``; deciding which optional surface to draw is a UI concern, and
    keeping that decision in a tested function beats inferring it from a
    ``ConfigurationError`` that also means "your credentials are missing".
    """
    return _ANALYSIS_PACK_ID in settings.domain_tools.enabled_packs
