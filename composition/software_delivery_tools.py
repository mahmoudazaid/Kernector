"""Composition-facing views for Software Delivery tool-run presentation.

Typed dataclasses only — no retrieval, orchestration, or invocation. #170 will
project tool outcomes onto these views before chat attaches them to
``AskResponse.tool_outputs``; #161 renders them in Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass

from composition.tool_runs import ToolCallView
from domain.knowledge import SourceReference
from infrastructure.config import Settings

_PACK_ID = "software-delivery"


@dataclass(frozen=True, slots=True)
class RiskFactorView:
    """One contributing risk factor with its supporting provenance."""

    factor_id: str
    weight: int
    references: tuple[SourceReference, ...]


@dataclass(frozen=True, slots=True)
class RiskScoreView:
    """Structured risk assessment exposed at the composition boundary."""

    score: int
    level: str
    rationale: str
    factors: tuple[RiskFactorView, ...]


@dataclass(frozen=True, slots=True)
class TestCaseView:
    """One generated test case with its provenance."""

    __test__ = False

    title: str
    steps: tuple[str, ...]
    expected: str
    references: tuple[SourceReference, ...]


@dataclass(frozen=True, slots=True)
class TestCasesView:
    """Generated test cases exposed at the composition boundary."""

    __test__ = False

    output_style: str
    cases: tuple[TestCaseView, ...]


@dataclass(frozen=True, slots=True)
class SoftwareDeliveryRunView:
    """Structured Software Delivery tool output for presentation."""

    summary: str
    calls: tuple[ToolCallView, ...]
    risk: RiskScoreView | None = None
    test_cases: TestCasesView | None = None
    markdown: str = ""


def software_delivery_tools_enabled(settings: Settings) -> bool:
    """Whether Software Delivery tool-result renderers may be shown."""
    return _PACK_ID in settings.domain_tools.enabled_packs
