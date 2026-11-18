"""Reusable component extraction port and collector (#387).

Framework-specific extractors live under ``extractors/`` so Robot, frontend,
Playwright, and future frameworks stay independently extendable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class OwnedReusableComponent:
    """Reusable item tagged with the evidence component it was extracted from.

    ``component_label`` is ``None`` for catalogue ``sources`` items that are not
    tied to a single evidence group.
    """

    component_label: str | None
    item: ReusableComponent


def collect_reusable_components(
    evidence: ProfileEvidence,
    *,
    extractors: Sequence[ComponentExtractor] = (),
    sources: Sequence[ReusableComponentSource] = (),
    return_diagnostics: bool = False,
    return_owners: bool = False,
):
    """Collect reusable components from extractors and catalogue sources.

    When ``return_owners`` is true, each extractor item is tagged with the
    evidence component label it came from. Catalogue ``sources`` items are
    tagged with ``component_label=None``.
    """
    collected: list[OwnedReusableComponent] = []
    diagnostics: list[str] = []
    for component in evidence.components:
        for extractor in extractors:
            items, diags = extractor.extract(component.label, component.files)
            collected.extend(
                OwnedReusableComponent(component.label, item) for item in items
            )
            diagnostics.extend(diags)
            if len(collected) >= MAX_REUSABLE_COMPONENTS:
                diagnostics.append("reusable component extraction limit reached")
                collected = collected[:MAX_REUSABLE_COMPONENTS]
                break
    for source in sources:
        for item in source.list_components(evidence):
            collected.append(OwnedReusableComponent(None, item))
            if len(collected) >= MAX_REUSABLE_COMPONENTS:
                diagnostics.append("reusable component extraction limit reached")
                collected = collected[:MAX_REUSABLE_COMPONENTS]
                break
    ordered = tuple(
        sorted(
            collected,
            key=lambda owned: (
                owned.item.kind,
                owned.item.path,
                owned.item.signature,
                owned.component_label or "",
            ),
        )
    )
    if return_owners:
        if return_diagnostics:
            return ordered, tuple(diagnostics)
        return ordered
    flat = tuple(owned.item for owned in ordered)
    if return_diagnostics:
        return flat, tuple(diagnostics)
    return flat


__all__ = [
    "ComponentExtractor",
    "FrontendPathExtractor",
    "OwnedReusableComponent",
    "PlaywrightSpecExtractor",
    "ReusableComponentSource",
    "RobotKeywordExtractor",
    "collect_reusable_components",
]
