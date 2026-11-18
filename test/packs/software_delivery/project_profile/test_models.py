"""TechnologyProfile contract invariants (#387 slice 1)."""

from __future__ import annotations

import dataclasses

import pytest

from packs.software_delivery.project_profile.errors import ProjectProfileValidationError
from packs.software_delivery.project_profile.fingerprint import profile_fingerprint
from packs.software_delivery.project_profile.models import (
    FACETS,
    FACET_STATUSES,
    PROFILE_CONFIDENCES,
    ComponentProfile,
    Convention,
    EvidenceRef,
    LineRange,
    ProfileFact,
    ReusableComponent,
    TechnologyProfile,
)


def _ref(**overrides: object) -> EvidenceRef:
    base = {
        "component": "oie-tests",
        "path": "resources/orders.resource",
        "content_hash": "abc123",
        "line_range": LineRange(2, 4),
    }
    base.update(overrides)
    return EvidenceRef(**base)  # type: ignore[arg-type]


def test_technology_profile_exposes_required_fields() -> None:
    names = {field.name for field in dataclasses.fields(TechnologyProfile)}
    assert names == {
        "profile_fingerprint",
        "evidence_origin",
        "facet_status",
        "facts",
        "conventions",
        "reusable_components",
        "approved_conventions",
        "conflicts",
        "diagnostics",
        "context_status",
        "untrusted_evidence",
        "components",
    }


def test_technology_profile_has_no_role_field() -> None:
    names = {field.name for field in dataclasses.fields(TechnologyProfile)}
    assert "role" not in names
    assert "user_role" not in names
    assert "team_role" not in names


def test_phase_a_empty_collections_and_untrusted_defaults() -> None:
    profile = TechnologyProfile(
        profile_fingerprint="fp",
        evidence_origin="client_supplied",
        facet_status={},
        facts=(),
        conventions=(),
        reusable_components=(),
        diagnostics=(),
        components=(),
    )
    assert profile.approved_conventions == ()
    assert profile.conflicts == ()
    assert profile.context_status == {}
    assert profile.untrusted_evidence is True


def test_evidence_ref_requires_component_path_hash_and_line_range() -> None:
    ref = _ref()
    assert ref.component == "oie-tests"
    assert ref.path == "resources/orders.resource"
    assert ref.content_hash == "abc123"
    assert ref.line_range == LineRange(2, 4)


def test_line_range_rejects_inverted_bounds() -> None:
    with pytest.raises(ProjectProfileValidationError):
        LineRange(5, 2)


def test_profile_fact_keeps_syntax_framework_and_type_separate() -> None:
    fact = ProfileFact(
        facet="specification_syntaxes",
        value="gherkin",
        confidence="high",
        evidence_refs=(_ref(),),
    )
    assert fact.framework_id is None
    assert "cucumber" not in fact.value.lower()
    assert FACETS >= {
        "specification_syntaxes",
        "test_frameworks",
        "languages",
        "application_frameworks",
        "delivery",
        "conventions",
        "reusable_components",
        "build_and_dependencies",
    }


def test_closed_vocabularies() -> None:
    assert FACET_STATUSES == frozenset(
        {"detected", "ambiguous", "insufficient_context", "unrecognized"}
    )
    assert PROFILE_CONFIDENCES == frozenset({"high", "medium", "low"})


def test_reusable_component_requires_full_contract() -> None:
    component = ReusableComponent(
        component_id="kw:create-unpaid-order",
        kind="keyword",
        framework_id="robot_framework",
        signature="Create Unpaid Order",
        path="resources/orders.resource",
        content_hash="abc123",
        line_range=LineRange(2, 4),
        documentation="Create an unpaid order for cancellation tests.",
    )
    names = {field.name for field in dataclasses.fields(component)}
    assert names == {
        "component_id",
        "kind",
        "framework_id",
        "signature",
        "path",
        "content_hash",
        "line_range",
        "documentation",
    }


def test_fingerprint_stable_under_reorder_and_sensitive_to_changes() -> None:
    evidence_a = (
        ("oie-orders", "pyproject.toml", "hash-a"),
        ("oie-tests", "requirements.txt", "hash-b"),
    )
    evidence_b = (
        ("oie-tests", "requirements.txt", "hash-b"),
        ("oie-orders", "pyproject.toml", "hash-a"),
    )
    detectors = (("python_manifest", "1"), ("robot_framework", "1"))
    fp_a = profile_fingerprint(evidence_a, detectors)
    fp_b = profile_fingerprint(evidence_b, detectors)
    assert fp_a == fp_b

    remapped = (
        ("other", "pyproject.toml", "hash-a"),
        ("oie-tests", "requirements.txt", "hash-b"),
    )
    assert profile_fingerprint(remapped, detectors) != fp_a

    bumped = (("python_manifest", "2"), ("robot_framework", "1"))
    assert profile_fingerprint(evidence_a, bumped) != fp_a

    revised = (
        ("oie-orders", "pyproject.toml", "hash-a-revised"),
        ("oie-tests", "requirements.txt", "hash-b"),
    )
    assert profile_fingerprint(revised, detectors) != fp_a


def test_convention_requires_evidence_refs() -> None:
    with pytest.raises(ProjectProfileValidationError):
        Convention(
            name="test_root",
            value="tests/",
            evidence_refs=(),
        )


def test_component_profile_carries_label_and_facet_status() -> None:
    component = ComponentProfile(
        label="oie-tests",
        facet_status={"test_frameworks": "detected"},
        facts=(),
        conventions=(),
        reusable_components=(),
        diagnostics=(),
    )
    assert component.label == "oie-tests"
    assert component.facet_status["test_frameworks"] == "detected"
