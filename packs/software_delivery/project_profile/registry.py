"""Technology detector registry and profile aggregation (#387)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Protocol

from packs.software_delivery.project_profile.fingerprint import profile_fingerprint
from packs.software_delivery.project_profile.intake import (
    EvidenceComponent,
    EvidenceFile,
    ProfileEvidence,
)
from packs.software_delivery.project_profile.limits import MAX_PROFILE_DIAGNOSTICS
from packs.software_delivery.project_profile.models import (
    FACETS,
    ComponentProfile,
    Convention,
    EvidenceRef,
    FacetStatus,
    ProfileFact,
    ReusableComponent,
    TechnologyProfile,
)

# Facets where multiple distinct values mean competing interpretations.
_COMPETING_FACETS = frozenset({"test_frameworks", "specification_syntaxes"})


@dataclass(frozen=True, slots=True)
class DetectorEmission:
    """One detector output item for a component.

    ``role`` and ``suite_ownership_key`` are pack-internal annotations used by
    aggregation. They are not part of the public ProfileFact / MCP contract.
    """

    fact: ProfileFact | None = None
    convention: Convention | None = None
    reusable_component: ReusableComponent | None = None
    unrecognized_facet: str | None = None
    diagnostic: str | None = None
    role: str | None = None
    suite_ownership_key: str | None = None


class TechnologyDetector(Protocol):
    """Deterministic, pack-provided technology detector plugin."""

    detector_id: str
    version: str
    facets: frozenset[str]
    # ClassVar matches detector implementations and avoids Protocol mutability
    # invariance on mapping attributes.
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]]

    def detect(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> list[DetectorEmission]:
        """Inspect evidence files and emit facts/conventions for one component."""
        ...


class TechnologyDetectorRegistry:
    """Ordered registry of technology detectors."""

    def __init__(self, detectors: Sequence[TechnologyDetector]) -> None:
        self._detectors = tuple(detectors)

    @property
    def detectors(self) -> tuple[TechnologyDetector, ...]:
        return self._detectors

    def detector_tuples(self) -> tuple[tuple[str, str], ...]:
        return tuple((d.detector_id, d.version) for d in self._detectors)


def recommendations_for_facet(
    registry: TechnologyDetectorRegistry, facet: str
) -> tuple[str, ...]:
    """Union evidence-path hints from detectors that own ``facet``, sorted."""
    found: set[str] = set()
    for detector in registry.detectors:
        if facet not in detector.facets:
            continue
        recommendations = getattr(detector, "evidence_recommendations", {}) or {}
        patterns = recommendations.get(facet, ())
        found.update(patterns)
    return tuple(sorted(found))


def _append_insufficient_hints(
    diagnostics: list[str], facet: str, recommendations: tuple[str, ...]
) -> None:
    """Append missing-evidence hints once (deduped across components)."""
    for recommendation in recommendations:
        message = f"insufficient_context for {facet}: provide {recommendation}"
        if message not in diagnostics:
            diagnostics.append(message)


def aggregate_profile(
    evidence: ProfileEvidence,
    registry: TechnologyDetectorRegistry,
    *,
    facets: frozenset[str] | None = None,
) -> TechnologyProfile:
    """Aggregate detector emissions into a TechnologyProfile.

    Provenance: facts/conventions whose evidence refs do not match intake are
    dropped. Competing values within a competing facet yield ``ambiguous``.
    Compatible multi-value facets stay ``detected``.
    """
    selected = facets if facets is not None else FACETS
    index = _evidence_index(evidence)
    component_profiles: list[ComponentProfile] = []
    all_facts: list[ProfileFact] = []
    all_conventions: list[Convention] = []
    all_components: list[ReusableComponent] = []
    diagnostics: list[str] = list(evidence.diagnostics)
    rollup_status: dict[str, FacetStatus] = {}

    declared_facets = frozenset().union(*(d.facets for d in registry.detectors)) & selected

    for component in evidence.components:
        profile = _aggregate_component(
            component,
            registry,
            index=index,
            selected=selected,
            declared_facets=declared_facets,
            diagnostics=diagnostics,
        )
        component_profiles.append(profile)
        all_facts.extend(profile.facts)
        all_conventions.extend(profile.conventions)
        all_components.extend(profile.reusable_components)
        for facet, status in profile.facet_status.items():
            previous = rollup_status.get(facet)
            if previous is None:
                rollup_status[facet] = status
            elif previous != status and status == "detected" and previous == "detected":
                rollup_status[facet] = "detected"
            elif previous == "ambiguous" or status == "ambiguous":
                # Ambiguity is per-component; project roll-up stays non-ambiguous
                # when each component is independently detected.
                if previous == "detected" and status == "detected":
                    rollup_status[facet] = "detected"
                elif previous == status:
                    rollup_status[facet] = status
                else:
                    # Prefer detected over insufficient when merging components.
                    rollup_status[facet] = _merge_rollup(previous, status)
            else:
                rollup_status[facet] = _merge_rollup(previous, status)

    evidence_tuples = tuple(
        (component.label, file.path, file.content_hash)
        for component in evidence.components
        for file in component.files
    )
    fingerprint = profile_fingerprint(evidence_tuples, registry.detector_tuples())

    return TechnologyProfile(
        profile_fingerprint=fingerprint,
        evidence_origin="client_supplied",
        facet_status=dict(sorted(rollup_status.items())),
        facts=tuple(all_facts),
        conventions=tuple(all_conventions),
        reusable_components=tuple(all_components),
        diagnostics=tuple(diagnostics[:MAX_PROFILE_DIAGNOSTICS]),
        components=tuple(
            sorted(component_profiles, key=lambda item: item.label)
        ),
        approved_conventions=(),
        conflicts=(),
        context_status={},
        untrusted_evidence=True,
    )


def _merge_rollup(left: FacetStatus, right: FacetStatus) -> FacetStatus:
    priority = {
        "detected": 3,
        "ambiguous": 2,
        "unrecognized": 1,
        "insufficient_context": 0,
    }
    # Never promote cross-component detected pairs to ambiguous.
    if left == "detected" and right == "detected":
        return "detected"
    if left == "ambiguous" and right == "detected":
        return "detected"
    if right == "ambiguous" and left == "detected":
        return "detected"
    return left if priority[left] >= priority[right] else right


@dataclass(frozen=True, slots=True)
class _AnnotatedFact:
    """Fact plus pack-internal emission annotations for aggregation."""

    fact: ProfileFact
    role: str | None
    suite_ownership_key: str | None


def _aggregate_component(
    component: EvidenceComponent,
    registry: TechnologyDetectorRegistry,
    *,
    index: dict[tuple[str, str, str], EvidenceFile],
    selected: frozenset[str],
    declared_facets: frozenset[str],
    diagnostics: list[str],
) -> ComponentProfile:
    facts_by_facet: dict[str, list[_AnnotatedFact]] = {}
    conventions: list[Convention] = []
    reusable: list[ReusableComponent] = []
    unrecognized: set[str] = set()
    component_diags: list[str] = []
    pending_unrecognized_diags: list[tuple[str, str]] = []

    for detector in registry.detectors:
        for emission in detector.detect(component.label, component.files):
            if emission.unrecognized_facet and emission.unrecognized_facet in selected:
                unrecognized.add(emission.unrecognized_facet)
                if emission.diagnostic:
                    pending_unrecognized_diags.append(
                        (emission.unrecognized_facet, emission.diagnostic)
                    )
            elif emission.diagnostic:
                # Multiple detectors may report the same malformed manifest;
                # keep a single copy so the diagnostic budget stays useful.
                if emission.diagnostic not in component_diags:
                    component_diags.append(emission.diagnostic)
            if emission.fact is not None and emission.fact.facet in selected:
                kept = _filter_fact(
                    emission.fact, index, diagnostics, component_label=component.label
                )
                if kept is not None:
                    facts_by_facet.setdefault(kept.facet, []).append(
                        _AnnotatedFact(
                            kept, emission.role, emission.suite_ownership_key
                        )
                    )
            if emission.convention is not None:
                kept_c = _filter_convention(
                    emission.convention,
                    index,
                    diagnostics,
                    component_label=component.label,
                )
                if kept_c is not None and "conventions" in selected:
                    conventions.append(kept_c)
            if emission.reusable_component is not None and "reusable_components" in selected:
                reusable.append(emission.reusable_component)

    # Facts from any detector supersede unrecognized claims for the same facet.
    unrecognized -= set(facts_by_facet)
    if conventions:
        unrecognized.discard("conventions")
    if reusable:
        unrecognized.discard("reusable_components")

    facet_status: dict[str, FacetStatus] = {}
    facts: list[ProfileFact] = []
    for facet in sorted(declared_facets):
        if facet == "conventions":
            if conventions:
                facet_status[facet] = "detected"
            elif facet in unrecognized:
                facet_status[facet] = "unrecognized"
            else:
                facet_status[facet] = "insufficient_context"
                _append_insufficient_hints(
                    diagnostics, facet, recommendations_for_facet(registry, facet)
                )
            continue
        if facet == "reusable_components":
            if reusable:
                facet_status[facet] = "detected"
            elif facet in unrecognized:
                facet_status[facet] = "unrecognized"
            else:
                facet_status[facet] = "insufficient_context"
                _append_insufficient_hints(
                    diagnostics, facet, recommendations_for_facet(registry, facet)
                )
            continue

        emitted = facts_by_facet.get(facet, [])
        if not emitted:
            if facet in unrecognized:
                facet_status[facet] = "unrecognized"
            else:
                facet_status[facet] = "insufficient_context"
                _append_insufficient_hints(
                    diagnostics, facet, recommendations_for_facet(registry, facet)
                )
            continue

        if facet in _COMPETING_FACETS:
            facet_status[facet] = _competing_facet_status(emitted)
        else:
            facet_status[facet] = "detected"
        facts.extend(
            sorted(
                (item.fact for item in emitted),
                key=lambda item: (item.value, item.framework_id or ""),
            )
        )

    for facet, diagnostic in pending_unrecognized_diags:
        if facet_status.get(facet) == "unrecognized":
            component_diags.append(diagnostic)
    diagnostics.extend(component_diags)
    return ComponentProfile(
        label=component.label,
        facet_status=dict(sorted(facet_status.items())),
        facts=tuple(facts),
        conventions=tuple(sorted(conventions, key=lambda item: item.name)),
        reusable_components=tuple(
            sorted(reusable, key=lambda item: (item.kind, item.path, item.signature))
        ),
        diagnostics=tuple(component_diags),
    )


def _competing_facet_status(emitted: Sequence[_AnnotatedFact]) -> FacetStatus:
    """Resolve competing-facet status using pack-internal role annotations.

    Different roles coexist as ``detected``. Same role with multiple identities
    is ``detected`` only when each identity has a distinct non-empty
    ``suite_ownership_key`` that does not path-prefix another; otherwise
    ``ambiguous``. Missing roles compete together so legacy multi-identity
    emissions stay ambiguous.
    """
    by_role: dict[str, list[_AnnotatedFact]] = {}
    for item in emitted:
        role_key = item.role if item.role else ""
        by_role.setdefault(role_key, []).append(item)

    for items in by_role.values():
        identity_keys: dict[str, set[str | None]] = {}
        for item in items:
            identity = item.fact.framework_id or item.fact.value
            identity_keys.setdefault(identity, set()).add(item.suite_ownership_key)
        if len(identity_keys) <= 1:
            continue
        ownership_values: list[str] = []
        for keys in identity_keys.values():
            concrete = {key for key in keys if key}
            if len(concrete) != 1:
                return "ambiguous"
            ownership_values.append(next(iter(concrete)))
        if _ownership_keys_overlap(ownership_values):
            return "ambiguous"
    return "detected"


def _ownership_keys_overlap(keys: Sequence[str]) -> bool:
    """True when any two ownership keys are equal or one path-prefixes the other."""
    norms = [key if key.endswith("/") else f"{key}/" for key in keys]
    for index, left in enumerate(norms):
        for right in norms[index + 1 :]:
            if left == right or left.startswith(right) or right.startswith(left):
                return True
    return False


def _evidence_index(
    evidence: ProfileEvidence,
) -> dict[tuple[str, str, str], EvidenceFile]:
    return {
        (component.label, file.path, file.content_hash): file
        for component in evidence.components
        for file in component.files
    }


def _filter_fact(
    fact: ProfileFact,
    index: dict[tuple[str, str, str], EvidenceFile],
    diagnostics: list[str],
    *,
    component_label: str,
) -> ProfileFact | None:
    valid = tuple(
        ref
        for ref in fact.evidence_refs
        if _ref_valid(ref, index, diagnostics, component_label=component_label)
    )
    if not valid:
        diagnostics.append(
            f"invalid evidence refs dropped fact {fact.facet}:{fact.value}"
        )
        return None
    if valid != fact.evidence_refs:
        return ProfileFact(
            facet=fact.facet,
            value=fact.value,
            confidence=fact.confidence,
            evidence_refs=valid,
            framework_id=fact.framework_id,
            language=fact.language,
        )
    return fact


def _filter_convention(
    convention: Convention,
    index: dict[tuple[str, str, str], EvidenceFile],
    diagnostics: list[str],
    *,
    component_label: str,
) -> Convention | None:
    valid = tuple(
        ref
        for ref in convention.evidence_refs
        if _ref_valid(ref, index, diagnostics, component_label=component_label)
    )
    if not valid:
        diagnostics.append(
            f"invalid evidence refs dropped convention {convention.name}"
        )
        return None
    if valid != convention.evidence_refs:
        return Convention(
            name=convention.name, value=convention.value, evidence_refs=valid
        )
    return convention


def _ref_valid(
    ref: EvidenceRef,
    index: dict[tuple[str, str, str], EvidenceFile],
    diagnostics: list[str],
    *,
    component_label: str,
) -> bool:
    if ref.component != component_label:
        diagnostics.append(
            f"cross-component evidence ref dropped: {ref.component}:{ref.path}"
        )
        return False
    file = index.get((ref.component, ref.path, ref.content_hash))
    if file is None:
        diagnostics.append(
            f"fabricated or mismatched evidence ref dropped: {ref.component}:{ref.path}"
        )
        return False
    line_count = len(file.content.splitlines()) if file.content else 0
    if ref.line_range.end > max(line_count, 1 if file.content else 0):
        diagnostics.append(
            f"fabricated evidence line_range dropped: {ref.component}:{ref.path}"
        )
        return False
    return True
