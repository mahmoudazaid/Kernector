"""Confirm a framework selection on a Test Design draft (#368).

Composition recomputes the #387 ``TechnologyProfile`` from client-supplied
project-profile evidence and passes that trusted profile here. This module
never accepts a client-built profile as authority and never reads draft issue
``client_evidence_text`` as profile evidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from packs.software_delivery.project_profile.models import (
    ComponentProfile,
    TechnologyProfile,
)
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.framework_contracts import (
    FrameworkResultStatus,
    FrameworkSelection,
)
from packs.software_delivery.test_design.models import TestCoverageDraft
from packs.software_delivery.test_design.repository import TestCoverageDraftRepository

_CONFIRMABLE_STATUSES = frozenset({"ready", "case_editing"})


@dataclass(frozen=True, slots=True)
class ConfirmFrameworkRequest:
    """Confirm framework against a recomputed profile (composition-trusted)."""

    draft_id: str
    expected_version: int
    framework_id: str
    profile: TechnologyProfile
    profile_fingerprint: str
    component_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConfirmFrameworkResult:
    """CAS-updated draft, or a typed non-ok status with no draft mutation."""

    status: FrameworkResultStatus
    draft: TestCoverageDraft | None = None
    framework_options: tuple[str, ...] = ()
    component_options: tuple[str, ...] = ()
    detail: str = ""


class ConfirmFrameworkSelection:
    """Persist ``FrameworkSelection`` on a draft via compare-and-swap."""

    def __init__(self, *, repository: TestCoverageDraftRepository) -> None:
        self._repository = repository

    def execute(self, request: ConfirmFrameworkRequest) -> ConfirmFrameworkResult:
        if not isinstance(request.expected_version, int) or isinstance(
            request.expected_version, bool
        ):
            raise TestDesignValidationError(
                "expected_version must be a positive integer"
            )
        if request.expected_version <= 0:
            raise TestDesignValidationError(
                "expected_version must be a positive integer"
            )
        if not isinstance(request.profile, TechnologyProfile):
            raise TestDesignValidationError(
                "profile must be a TechnologyProfile recomputed by composition"
            )
        if not isinstance(request.profile_fingerprint, str) or not (
            request.profile_fingerprint.strip()
        ):
            raise TestDesignValidationError("profile_fingerprint must be non-empty")
        if request.profile_fingerprint != request.profile.profile_fingerprint:
            raise TestDesignValidationError(
                "profile_fingerprint does not match recomputed profile"
            )

        draft = self._repository.get(request.draft_id)
        if draft is None:
            raise TestDesignValidationError("draft not found")
        if draft.version != request.expected_version:
            raise TestDesignValidationError("version conflict")
        if draft.status not in _CONFIRMABLE_STATUSES:
            raise TestDesignValidationError(
                "confirm framework requires a confirmed coverage draft"
            )

        automation = _automation_components(request.profile)
        if not automation:
            return ConfirmFrameworkResult(
                status="profile_required",
                detail="no test frameworks detected in profile",
            )

        component = _resolve_component(
            automation, request.component_id, request.framework_id
        )
        if isinstance(component, ConfirmFrameworkResult):
            return component

        frameworks = _framework_ids(component)
        facet = component.facet_status.get("test_frameworks", "insufficient_context")
        framework_id = (
            request.framework_id.strip()
            if isinstance(request.framework_id, str)
            else ""
        )

        if facet == "insufficient_context" or not frameworks:
            return ConfirmFrameworkResult(
                status="profile_required",
                detail="test_frameworks facet has insufficient context",
                component_options=tuple(c.label for c in automation),
            )

        if not framework_id:
            return ConfirmFrameworkResult(
                status="framework_choice_required",
                framework_options=frameworks,
                component_options=(component.label,),
                detail="choose a framework_id explicitly",
            )

        if framework_id not in frameworks:
            raise TestDesignValidationError(
                f"framework_id {framework_id} is not in the profile for "
                f"component {component.label}"
            )

        selection = FrameworkSelection(
            component_id=component.label,
            framework_id=framework_id,
            profile_fingerprint=request.profile.profile_fingerprint,
            evidence_origin="client_supplied",
            conventions=tuple(
                c
                for c in component.conventions
                if True  # bounded to this component already
            ),
            reusable_components=tuple(
                item
                for item in component.reusable_components
                if item.framework_id == framework_id
            ),
            confirmed_at_version=draft.version,
        )
        updated = replace(draft, framework_selection=selection)
        saved = self._repository.update(
            updated, expected_version=request.expected_version
        )
        return ConfirmFrameworkResult(status="ok", draft=saved)


def _automation_components(profile: TechnologyProfile) -> tuple[ComponentProfile, ...]:
    found: list[ComponentProfile] = []
    for component in profile.components:
        if _framework_ids(component):
            found.append(component)
        elif component.facet_status.get("test_frameworks") in {
            "ambiguous",
            "detected",
            "insufficient_context",
        }:
            # Include components that declare the facet even without ids yet.
            if any(f.facet == "test_frameworks" for f in component.facts):
                found.append(component)
    if found:
        return tuple(found)
    # Fall back to project-level facts when components are empty/implicit.
    if profile.facts and any(f.facet == "test_frameworks" for f in profile.facts):
        return (
            ComponentProfile(
                label="",
                facet_status=profile.facet_status,
                facts=profile.facts,
                conventions=profile.conventions,
                reusable_components=profile.reusable_components,
                diagnostics=profile.diagnostics,
            ),
        )
    return ()


def _framework_ids(component: ComponentProfile) -> tuple[str, ...]:
    ids: list[str] = []
    seen: set[str] = set()
    for fact in component.facts:
        if fact.facet != "test_frameworks":
            continue
        framework_id = fact.framework_id or fact.value
        if framework_id and framework_id not in seen:
            seen.add(framework_id)
            ids.append(framework_id)
    return tuple(ids)


def _resolve_component(
    automation: Sequence[ComponentProfile],
    component_id: str | None,
    framework_id: str,
) -> ComponentProfile | ConfirmFrameworkResult:
    if len(automation) > 1:
        label = component_id.strip() if isinstance(component_id, str) else ""
        if not label:
            return ConfirmFrameworkResult(
                status="framework_choice_required",
                component_options=tuple(c.label for c in automation),
                framework_options=tuple(
                    sorted(
                        {
                            fid
                            for component in automation
                            for fid in _framework_ids(component)
                        }
                    )
                ),
                detail="component_id is required when multiple automation components exist",
            )
        for component in automation:
            if component.label == label:
                return component
        raise TestDesignValidationError(
            f"component_id {label} is not an automation component in the profile"
        )

    only = automation[0]
    if (
        isinstance(component_id, str)
        and component_id.strip()
        and component_id.strip() != only.label
        and only.label != ""
    ):
        raise TestDesignValidationError(
            f"component_id {component_id.strip()} is not an automation "
            f"component in the profile"
        )
    return only
