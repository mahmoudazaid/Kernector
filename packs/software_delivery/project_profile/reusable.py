"""Reusable component extraction port and collector (#387).

Framework-specific extractors live under ``extractors/`` so Robot, frontend,
Playwright, and future frameworks stay independently extendable.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from packs.software_delivery.project_profile.intake import (
    EvidenceFile,
    ProfileEvidence,
)
from packs.software_delivery.project_profile.limits import MAX_REUSABLE_COMPONENTS
from packs.software_delivery.project_profile.models import ReusableComponent

# Re-export MVP extractors for existing imports.
from packs.software_delivery.project_profile.extractors.frontend_paths import (  # noqa: E402
    FrontendPathExtractor,
)
from packs.software_delivery.project_profile.extractors.playwright_specs import (  # noqa: E402
    PlaywrightSpecExtractor,
)
from packs.software_delivery.project_profile.extractors.robot_keywords import (  # noqa: E402
    RobotKeywordExtractor,
)


class ReusableComponentSource(Protocol):
    """Port for persistent catalogues such as #298 Cucumber step definitions."""

    def list_components(
        self, evidence: ProfileEvidence
    ) -> Sequence[ReusableComponent]:
        """Return components whose provenance must be preserved unchanged."""
        ...


class ComponentExtractor(Protocol):
    """Extract reusable components from client-supplied evidence files."""

    def extract(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> tuple[tuple[ReusableComponent, ...], tuple[str, ...]]:
        """Return components and sanitized diagnostics."""
        ...


def collect_reusable_components(
    evidence: ProfileEvidence,
    *,
    extractors: Sequence[ComponentExtractor] = (),
    sources: Sequence[ReusableComponentSource] = (),
    return_diagnostics: bool = False,
):
    """Collect reusable components from extractors and catalogue sources."""
    collected: list[ReusableComponent] = []
    diagnostics: list[str] = []
    for component in evidence.components:
        for extractor in extractors:
            items, diags = extractor.extract(component.label, component.files)
            collected.extend(items)
            diagnostics.extend(diags)
            if len(collected) >= MAX_REUSABLE_COMPONENTS:
                diagnostics.append("reusable component extraction limit reached")
                collected = collected[:MAX_REUSABLE_COMPONENTS]
                break
    for source in sources:
        for item in source.list_components(evidence):
            collected.append(item)
            if len(collected) >= MAX_REUSABLE_COMPONENTS:
                diagnostics.append("reusable component extraction limit reached")
                collected = collected[:MAX_REUSABLE_COMPONENTS]
                break
    ordered = tuple(
        sorted(collected, key=lambda item: (item.kind, item.path, item.signature))
    )
    if return_diagnostics:
        return ordered, tuple(diagnostics)
    return ordered


__all__ = [
    "ComponentExtractor",
    "FrontendPathExtractor",
    "PlaywrightSpecExtractor",
    "ReusableComponentSource",
    "RobotKeywordExtractor",
    "collect_reusable_components",
]
