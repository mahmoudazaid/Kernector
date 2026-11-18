"""Composition adapter: project profile MCP binding (#387 Phase A)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from composition.project_profile.facade import ProjectProfileFacade
from domain.errors import ToolArgumentValidationError
from infrastructure.config import Settings
from packs.software_delivery.project_profile.errors import ProjectProfileValidationError
from packs.software_delivery.project_profile.models import (
    FACETS,
    TechnologyProfile,
)

FacetName = Literal[
    "languages",
    "build_and_dependencies",
    "application_frameworks",
    "test_frameworks",
    "specification_syntaxes",
    "delivery",
    "conventions",
    "reusable_components",
]

ComponentLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=128)
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceFileArgs(_Strict):
    path: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
    content: str


class EvidenceGroupArgs(_Strict):
    files: list[EvidenceFileArgs] = Field(min_length=1)
    component: ComponentLabel | None = None


class ProjectProfileArgs(_Strict):
    evidence: list[EvidenceGroupArgs] = Field(min_length=1)
    facets: list[FacetName] | None = None

    @field_validator("facets")
    @classmethod
    def _known_facets(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        unknown = set(value) - set(FACETS)
        if unknown:
            raise ValueError(f"unknown facets: {sorted(unknown)}")
        return value


class LineRangeOut(_Strict):
    start: int
    end: int


class EvidenceRefOut(_Strict):
    component: str
    path: str
    content_hash: str
    line_range: LineRangeOut


class ProfileFactOut(_Strict):
    facet: str
    value: str
    confidence: str
    evidence_refs: list[EvidenceRefOut]
    framework_id: str | None = None
    language: str | None = None


class ConventionOut(_Strict):
    name: str
    value: str
    evidence_refs: list[EvidenceRefOut]


class ReusableComponentOut(_Strict):
    component_id: str
    kind: str
    framework_id: str
    signature: str
    path: str
    content_hash: str
    line_range: LineRangeOut
    documentation: str


class ComponentProfileOut(_Strict):
    label: str
    facet_status: dict[str, str]
    facts: list[ProfileFactOut]
    conventions: list[ConventionOut]
    reusable_components: list[ReusableComponentOut]
    diagnostics: list[str]


class ProjectProfileResult(_Strict):
    profile_fingerprint: str
    evidence_origin: str
    facet_status: dict[str, str]
    facts: list[ProfileFactOut]
    conventions: list[ConventionOut]
    reusable_components: list[ReusableComponentOut]
    approved_conventions: list[object]
    conflicts: list[object]
    diagnostics: list[str]
    context_status: dict[str, object]
    untrusted_evidence: bool
    components: list[ComponentProfileOut]


class McpProjectProfileWorkflow:
    def __init__(self, facade: ProjectProfileFacade) -> None:
        self._facade = facade

    def profile(self, arguments: Mapping[str, object]) -> Mapping[str, object]:
        if "project_id" in arguments:
            raise ToolArgumentValidationError(
                "project_id is not supported in Phase A; supply evidence"
            )
        try:
            args = ProjectProfileArgs.model_validate(dict(arguments))
        except Exception as exc:
            raise ToolArgumentValidationError(
                "Invalid project_profile arguments"
            ) from exc
        groups = []
        for group in args.evidence:
            item: dict[str, object] = {
                "files": [
                    {"path": f.path, "content": f.content} for f in group.files
                ]
            }
            if group.component is not None:
                item["component"] = group.component
            groups.append(item)
        try:
            result = self._facade.profile(groups, facets=args.facets)
        except ProjectProfileValidationError as exc:
            raise ToolArgumentValidationError(str(exc)) from exc
        return _project_profile(result)


class McpProjectProfileBinding:
    args: type = ProjectProfileArgs
    result: type = ProjectProfileResult

    def __init__(self, facade_factory: Callable[[], ProjectProfileFacade]) -> None:
        self._facade_factory = facade_factory

    def workflow(self) -> McpProjectProfileWorkflow:
        return McpProjectProfileWorkflow(self._facade_factory())


def build_mcp_project_profile_binding(
    settings: Settings,
    *,
    facade_factory: Callable[[], ProjectProfileFacade] | None = None,
) -> McpProjectProfileBinding:
    """Return a project-profile MCP binding scoped to the server workspace."""

    def _facade() -> ProjectProfileFacade:
        if facade_factory is not None:
            return facade_factory()
        workspace_id = settings.document_catalog.workspace_id or "default"
        return ProjectProfileFacade(workspace_id)

    return McpProjectProfileBinding(_facade)


def _project_profile(profile: TechnologyProfile) -> dict[str, object]:
    return ProjectProfileResult(
        profile_fingerprint=profile.profile_fingerprint,
        evidence_origin=profile.evidence_origin,
        facet_status=dict(profile.facet_status),
        facts=[_fact(f) for f in profile.facts],
        conventions=[_convention(c) for c in profile.conventions],
        reusable_components=[_reusable(r) for r in profile.reusable_components],
        approved_conventions=list(profile.approved_conventions),
        conflicts=list(profile.conflicts),
        diagnostics=list(profile.diagnostics),
        context_status=dict(profile.context_status),
        untrusted_evidence=profile.untrusted_evidence,
        components=[
            ComponentProfileOut(
                label=component.label,
                facet_status=dict(component.facet_status),
                facts=[_fact(f) for f in component.facts],
                conventions=[_convention(c) for c in component.conventions],
                reusable_components=[
                    _reusable(r) for r in component.reusable_components
                ],
                diagnostics=list(component.diagnostics),
            )
            for component in profile.components
        ],
    ).model_dump(mode="json")


def _fact(fact) -> ProfileFactOut:
    return ProfileFactOut(
        facet=fact.facet,
        value=fact.value,
        confidence=fact.confidence,
        framework_id=fact.framework_id,
        language=fact.language,
        evidence_refs=[_ref(r) for r in fact.evidence_refs],
    )


def _convention(convention) -> ConventionOut:
    return ConventionOut(
        name=convention.name,
        value=convention.value,
        evidence_refs=[_ref(r) for r in convention.evidence_refs],
    )


def _reusable(item) -> ReusableComponentOut:
    return ReusableComponentOut(
        component_id=item.component_id,
        kind=item.kind,
        framework_id=item.framework_id,
        signature=item.signature,
        path=item.path,
        content_hash=item.content_hash,
        line_range=LineRangeOut(
            start=item.line_range.start, end=item.line_range.end
        ),
        documentation=item.documentation,
    )


def _ref(ref) -> EvidenceRefOut:
    return EvidenceRefOut(
        component=ref.component,
        path=ref.path,
        content_hash=ref.content_hash,
        line_range=LineRangeOut(
            start=ref.line_range.start, end=ref.line_range.end
        ),
    )
