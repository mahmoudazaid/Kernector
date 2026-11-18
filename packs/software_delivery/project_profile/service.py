"""Compose detectors and reusable extractors into a TechnologyProfile (#387)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from packs.software_delivery.project_profile.detectors import default_detector_registry
from packs.software_delivery.project_profile.intake import (
    ProfileEvidence,
    ingest_profile_evidence,
)
from packs.software_delivery.project_profile.limits import MAX_PROFILE_DIAGNOSTICS
from packs.software_delivery.project_profile.models import (
    FACETS,
    ComponentProfile,
    TechnologyProfile,
)
from packs.software_delivery.project_profile.registry import (
    TechnologyDetectorRegistry,
    aggregate_profile,
)
from packs.software_delivery.project_profile.extractors import default_extractors
from packs.software_delivery.project_profile.reusable import (
    ComponentExtractor,
    OwnedReusableComponent,
    ReusableComponentSource,
    collect_reusable_components,
)


def profile_project(
    evidence_groups: object,
    *,
    facets: Sequence[str] | None = None,
    registry: TechnologyDetectorRegistry | None = None,
    extractors: Sequence[ComponentExtractor] | None = None,
    sources: Sequence[ReusableComponentSource] = (),
) -> TechnologyProfile:
    """Profile client-supplied evidence into a TechnologyProfile.

    Phase A: ``evidence_groups`` only. No ``project_id`` path.
    """
    selected = _selected_facets(facets)
    evidence = ingest_profile_evidence(evidence_groups)
    detectors = registry or default_detector_registry()
    profile = aggregate_profile(evidence, detectors, facets=selected)
    active_extractors = (
        extractors if extractors is not None else default_extractors()
    )
    reusable, extract_diags = collect_reusable_components(
        evidence,
        extractors=active_extractors,
        sources=sources,
        return_diagnostics=True,
        return_owners=True,
    )
    if "reusable_components" not in selected:
        reusable = ()
    return _merge_reusable(profile, evidence, reusable, extract_diags, selected)


def _selected_facets(facets: Sequence[str] | None) -> frozenset[str]:
    if facets is None:
        return FACETS
    selected = frozenset(facets)
    unknown = selected - FACETS
    if unknown:
        from packs.software_delivery.project_profile.errors import (
            ProjectProfileValidationError,
        )

        names = ", ".join(sorted(map(str, unknown)))
        raise ProjectProfileValidationError(f"unknown facets: {names}")
    return selected or FACETS


def _merge_reusable(
    profile: TechnologyProfile,
    evidence: ProfileEvidence,
    reusable: tuple[OwnedReusableComponent, ...],
    extract_diags: tuple[str, ...],
    selected: frozenset[str],
) -> TechnologyProfile:
    diagnostics = (
        list(profile.diagnostics) + list(extract_diags)
    )[:MAX_PROFILE_DIAGNOSTICS]
    by_component: dict[str, list] = {c.label: [] for c in evidence.components}
    unmatched = []
    for owned in reusable:
        if owned.component_label is None:
            unmatched.append(owned.item)
            continue
        by_component.setdefault(owned.component_label, []).append(owned.item)

    components: list[ComponentProfile] = []
    for component in profile.components:
        items = tuple(
            sorted(
                by_component.get(component.label, []),
                key=lambda item: (item.kind, item.path, item.signature),
            )
        )
        facet_status = dict(component.facet_status)
        if "reusable_components" in selected:
            facet_status["reusable_components"] = (
                "detected" if items else facet_status.get(
                    "reusable_components", "insufficient_context"
                )
            )
            if items:
                facet_status["reusable_components"] = "detected"
        components.append(
            replace(
                component,
                reusable_components=items if "reusable_components" in selected else (),
                facet_status=dict(sorted(facet_status.items())),
            )
        )

    all_reusable = tuple(
        sorted(
            [item for c in components for item in c.reusable_components] + unmatched,
            key=lambda item: (item.kind, item.path, item.signature),
        )
    )
    rollup = dict(profile.facet_status)
    if "reusable_components" in selected:
        rollup["reusable_components"] = (
            "detected" if all_reusable else rollup.get(
                "reusable_components", "insufficient_context"
            )
        )
        if all_reusable:
            rollup["reusable_components"] = "detected"

    return replace(
        profile,
        components=tuple(components),
        reusable_components=all_reusable if "reusable_components" in selected else (),
        facet_status=dict(sorted(rollup.items())),
        diagnostics=tuple(diagnostics),
        facts=tuple(f for f in profile.facts if f.facet in selected),
        conventions=tuple(profile.conventions)
        if "conventions" in selected
        else (),
    )
