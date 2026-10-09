"""Project Intelligence domain contracts (#372, ADR 0011)."""

from __future__ import annotations

import pytest

from domain.errors import DomainValidationError
from domain.knowledge import SourceReference
from domain.project.errors import ProjectInputError
from domain.project.models import (
    AssociationState,
    ComponentMember,
    ComponentResolution,
    ComponentResolutionStatus,
    ContextAssociationCoverage,
    ContextAssociationStatus,
    Project,
    ProjectComponent,
    SourceAssociation,
    SourceScope,
    can_transition,
    new_component_id,
    new_project_id,
)

ORDERS = SourceScope("gh-1", "repo", "acme/oie-orders")


def _association(**overrides: object) -> SourceAssociation:
    values: dict[str, object] = {
        "project_id": "prj_oie",
        "scope": ORDERS,
        "roles": ("backend", "api_contract"),
        "state": AssociationState.CONFIRMED,
        "evidence": (),
        "created_by": "operator",
        "version": 1,
    }
    values.update(overrides)
    return SourceAssociation(**values)  # type: ignore[arg-type]


def test_project_accepts_adr_0006_identifier_shape() -> None:
    project = Project("prj_7f3a", "Order Intake", "order-intake", 1)

    assert project.project_id == "prj_7f3a"


@pytest.mark.parametrize("project_id", ["", "bad id", "a/b", "x" * 65, "prj:1"])
def test_project_rejects_invalid_identifier(project_id: str) -> None:
    with pytest.raises(ProjectInputError):
        Project(project_id, "Name", "slug", 1)


@pytest.mark.parametrize("slug", ["", "Upper", "two  spaces", "-lead", "trail-", "a_b"])
def test_project_rejects_invalid_slug(slug: str) -> None:
    with pytest.raises(ProjectInputError):
        Project("prj_1", "Name", slug, 1)


@pytest.mark.parametrize("version", [0, -1, True])
def test_project_rejects_non_positive_version(version: object) -> None:
    with pytest.raises(ProjectInputError):
        Project("prj_1", "Name", "slug", version)  # type: ignore[arg-type]


def test_project_rejects_blank_name() -> None:
    with pytest.raises(ProjectInputError):
        Project("prj_1", "   ", "slug", 1)


def test_project_errors_are_domain_validation_errors() -> None:
    with pytest.raises(DomainValidationError):
        Project("bad id", "Name", "slug", 1)


def test_generated_ids_are_valid_and_unique() -> None:
    first, second = new_project_id(), new_project_id()

    assert first.startswith("prj_") and first != second
    assert Project(first, "Name", "slug", 1).project_id == first
    assert new_component_id().startswith("cmp_")


@pytest.mark.parametrize(
    "connector_id,scope_kind,scope_value",
    [
        ("", "repo", "acme/x"),
        ("gh-1", "", "acme/x"),
        ("gh-1", "Repo", "acme/x"),
        ("gh-1", "repo kind", "acme/x"),
        ("gh-1", "repo", ""),
        ("gh-1", "repo", "acme/\nx"),
        ("gh\x00", "repo", "acme/x"),
    ],
)
def test_scope_rejects_invalid_tokens(
    connector_id: str, scope_kind: str, scope_value: str
) -> None:
    with pytest.raises(ProjectInputError):
        SourceScope(connector_id, scope_kind, scope_value)


def test_scope_is_an_opaque_value() -> None:
    assert SourceScope("jira-1", "project_key", "OIE") == SourceScope(
        "jira-1", "project_key", "OIE"
    )


def test_association_keeps_multiple_roles_in_order() -> None:
    assert _association().roles == ("backend", "api_contract")


def test_association_allows_zero_roles() -> None:
    assert _association(roles=()).roles == ()


@pytest.mark.parametrize(
    "roles", [("backend", "backend"), ("Backend",), ("",), "backend"]
)
def test_association_rejects_invalid_roles(roles: object) -> None:
    with pytest.raises(ProjectInputError):
        _association(roles=roles)


def test_association_evidence_must_be_source_references() -> None:
    evidence = (SourceReference("site/OIE:OIE-1", "jira"),)

    assert _association(evidence=evidence).evidence == evidence
    with pytest.raises(ProjectInputError):
        _association(evidence=("OIE-1",))


def test_association_requires_actor_and_state() -> None:
    with pytest.raises(ProjectInputError):
        _association(created_by=" ")
    with pytest.raises(ProjectInputError):
        _association(state="confirmed")


@pytest.mark.parametrize(
    "current,target,allowed",
    [
        (AssociationState.SUGGESTED, AssociationState.CONFIRMED, True),
        (AssociationState.SUGGESTED, AssociationState.REJECTED, True),
        (AssociationState.REJECTED, AssociationState.CONFIRMED, True),
        (AssociationState.CONFIRMED, AssociationState.CONFIRMED, False),
        (AssociationState.CONFIRMED, AssociationState.SUGGESTED, False),
        (AssociationState.REJECTED, AssociationState.SUGGESTED, False),
    ],
)
def test_association_state_transitions(
    current: AssociationState, target: AssociationState, allowed: bool
) -> None:
    assert can_transition(current, target) is allowed


def test_component_member_requires_canonical_prefix() -> None:
    assert ComponentMember(ORDERS, "web").path_prefix == "web"
    assert ComponentMember(ORDERS).path_prefix == ""
    with pytest.raises(ProjectInputError):
        ComponentMember(ORDERS, "web/")


def test_component_requires_unique_members() -> None:
    member = ComponentMember(ORDERS, "")
    component = ProjectComponent(
        "cmp_1", "prj_oie", "oie-orders", (member,), "association_default", 1
    )

    assert component.members == (member,)
    with pytest.raises(ProjectInputError):
        ProjectComponent("cmp_1", "prj_oie", "x", (), "operator", 1)
    with pytest.raises(ProjectInputError):
        ProjectComponent("cmp_1", "prj_oie", "x", (member, member), "operator", 1)


def test_context_coverage_status_matches_scopes() -> None:
    associated = ContextAssociationCoverage(
        "backend", ContextAssociationStatus.ASSOCIATED, (ORDERS,)
    )

    assert associated.status == "associated"
    assert ContextAssociationStatus.NOT_ASSOCIATED == "not_associated"
    with pytest.raises(ProjectInputError):
        ContextAssociationCoverage("backend", ContextAssociationStatus.ASSOCIATED, ())
    with pytest.raises(ProjectInputError):
        ContextAssociationCoverage(
            "backend", ContextAssociationStatus.NOT_ASSOCIATED, (ORDERS,)
        )


@pytest.mark.parametrize(
    "status,ids,valid",
    [
        (ComponentResolutionStatus.RESOLVED, ("cmp_1",), True),
        (ComponentResolutionStatus.RESOLVED, (), False),
        (ComponentResolutionStatus.AMBIGUOUS, ("cmp_1", "cmp_2"), True),
        (ComponentResolutionStatus.AMBIGUOUS, ("cmp_1",), False),
        (ComponentResolutionStatus.UNASSIGNED, (), True),
        (ComponentResolutionStatus.INVALID_PATH, ("cmp_1",), False),
    ],
)
def test_component_resolution_shape(
    status: ComponentResolutionStatus, ids: tuple[str, ...], valid: bool
) -> None:
    if valid:
        assert ComponentResolution("prj_oie", status, ids).component_ids == ids
    else:
        with pytest.raises(ProjectInputError):
            ComponentResolution("prj_oie", status, ids)
