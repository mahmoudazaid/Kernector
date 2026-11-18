"""Contracts for client-supplied technology profiles (#387 Phase A)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from packs.software_delivery.project_profile.errors import ProjectProfileValidationError

FacetStatus = Literal[
    "detected", "ambiguous", "insufficient_context", "unrecognized"
]
ProfileConfidence = Literal["high", "medium", "low"]
EvidenceOrigin = Literal["client_supplied"]

FACETS: frozenset[str] = frozenset(
    {
        "languages",
        "build_and_dependencies",
        "application_frameworks",
        "test_frameworks",
        "specification_syntaxes",
        "delivery",
        "conventions",
        "reusable_components",
    }
)
FACET_STATUSES: frozenset[str] = frozenset(
    {"detected", "ambiguous", "insufficient_context", "unrecognized"}
)
PROFILE_CONFIDENCES: frozenset[str] = frozenset({"high", "medium", "low"})
IMPLICIT_COMPONENT = ""


@dataclass(frozen=True, slots=True)
class LineRange:
    """1-based inclusive line range within an evidence file."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 1 or self.end < 1 or self.end < self.start:
            raise ProjectProfileValidationError(
                "line_range must be 1-based with end >= start"
            )


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Citation into client-supplied evidence for a profile fact."""

    component: str
    path: str
    content_hash: str
    line_range: LineRange


@dataclass(frozen=True, slots=True)
class ProfileFact:
    """One detected technology or configuration fact."""

    facet: str
    value: str
    confidence: ProfileConfidence
    evidence_refs: tuple[EvidenceRef, ...]
    framework_id: str | None = None
    language: str | None = None


@dataclass(frozen=True, slots=True)
class Convention:
    """A project convention cited from evidence."""

    name: str
    value: str
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if not self.evidence_refs:
            raise ProjectProfileValidationError(
                "convention must cite at least one evidence_ref"
            )


@dataclass(frozen=True, slots=True)
class ReusableComponent:
    """A reusable automation or frontend component discovered from evidence."""

    component_id: str
    kind: str
    framework_id: str
    signature: str
    path: str
    content_hash: str
    line_range: LineRange
    documentation: str


@dataclass(frozen=True, slots=True)
class ComponentProfile:
    """Technology profile for one client-declared (or implicit) component."""

    label: str
    facet_status: Mapping[str, FacetStatus]
    facts: tuple[ProfileFact, ...]
    conventions: tuple[Convention, ...]
    reusable_components: tuple[ReusableComponent, ...]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TechnologyProfile:
    """Ephemeral, untrusted technology profile over project evidence."""

    profile_fingerprint: str
    evidence_origin: EvidenceOrigin
    facet_status: Mapping[str, FacetStatus]
    facts: tuple[ProfileFact, ...]
    conventions: tuple[Convention, ...]
    reusable_components: tuple[ReusableComponent, ...]
    diagnostics: tuple[str, ...]
    components: tuple[ComponentProfile, ...]
    approved_conventions: tuple[object, ...] = field(default_factory=tuple)
    conflicts: tuple[object, ...] = field(default_factory=tuple)
    context_status: Mapping[str, object] = field(default_factory=dict)
    untrusted_evidence: bool = True
