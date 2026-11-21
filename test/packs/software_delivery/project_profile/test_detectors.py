"""MVP detectors against Part A0 fixture and variants (#387 slice 4)."""

from __future__ import annotations

from test.packs.software_delivery.project_profile.conftest import (
    a0_evidence,
    variant_evidence,
)
from test.fixtures.project_intelligence.loader import secret_env_value

from packs.software_delivery.project_profile.detectors import default_detector_registry
from packs.software_delivery.project_profile.registry import aggregate_profile


def test_a0_orders_detects_python_and_delivery() -> None:
    profile = aggregate_profile(a0_evidence(), default_detector_registry())
    orders = next(c for c in profile.components if c.label == "oie-orders")
    assert orders.facet_status["languages"] == "detected"
    assert any(f.value == "Python" for f in orders.facts if f.facet == "languages")
    assert orders.facet_status["delivery"] == "detected"
    delivery = {f.value for f in orders.facts if f.facet == "delivery"}
    assert "github_actions" in delivery
    assert "docker" in delivery
    secret = secret_env_value()
    assert secret not in "\n".join(profile.diagnostics)
    assert all(secret not in f.value for f in profile.facts)


def test_a0_tests_detects_robot_not_ambiguous_with_e2e() -> None:
    profile = aggregate_profile(a0_evidence(), default_detector_registry())
    by_label = {c.label: c for c in profile.components}
    assert by_label["oie-tests"].facet_status["test_frameworks"] == "detected"
    assert any(
        f.framework_id == "robot_framework"
        for f in by_label["oie-tests"].facts
        if f.facet == "test_frameworks"
    )
    assert by_label["oie-e2e"].facet_status["test_frameworks"] == "detected"
    assert any(
        f.framework_id == "playwright"
        for f in by_label["oie-e2e"].facts
        if f.facet == "test_frameworks"
    )
    assert profile.facet_status.get("test_frameworks") != "ambiguous"


def test_a0_web_detects_typescript_next_react() -> None:
    profile = aggregate_profile(a0_evidence(), default_detector_registry())
    web = next(c for c in profile.components if c.label == "oie-web")
    assert web.facet_status["languages"] == "detected"
    assert any(f.value == "TypeScript" for f in web.facts if f.facet == "languages")
    frameworks = {
        f.framework_id
        for f in web.facts
        if f.facet == "application_frameworks"
    }
    assert {"next", "react"} <= frameworks
    assert web.facet_status["application_frameworks"] == "detected"


def test_every_fact_cites_valid_input_evidence() -> None:
    evidence = a0_evidence()
    profile = aggregate_profile(evidence, default_detector_registry())
    index = {
        (c.label, f.path, f.content_hash)
        for c in evidence.components
        for f in c.files
    }
    for fact in profile.facts:
        assert fact.evidence_refs
        for ref in fact.evidence_refs:
            assert (ref.component, ref.path, ref.content_hash) in index


def test_delivery_reports_env_names_not_values() -> None:
    profile = aggregate_profile(a0_evidence(), default_detector_registry())
    orders = next(c for c in profile.components if c.label == "oie-orders")
    delivery_facts = [f for f in orders.facts if f.facet == "delivery"]
    blob = "\n".join(f.value for f in delivery_facts)
    assert "DATABASE_URL" in "\n".join(orders.diagnostics) or any(
        "DATABASE_URL" in (f.value or "") for f in delivery_facts
    ) or any("env:" in d for d in profile.diagnostics + orders.diagnostics)
    # Secret fixture values must never appear
    assert secret_env_value() not in blob
    assert "super-secret-password-never-leak" not in "\n".join(profile.diagnostics)


def test_delivery_detects_gitlab_jenkins_and_compose() -> None:
    from packs.software_delivery.project_profile.intake import ingest_profile_evidence

    evidence = ingest_profile_evidence(
        [
            {
                "files": [
                    {"path": ".gitlab-ci.yml", "content": "stages: [test]\n"},
                    {"path": "Jenkinsfile", "content": "pipeline { agent any }\n"},
                    {
                        "path": "docker-compose.yml",
                        "content": "services:\n  api:\n    image: api\n",
                    },
                ]
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    delivery = {f.value for f in profile.facts if f.facet == "delivery"}
    assert {"gitlab_ci", "jenkins", "docker_compose"} <= delivery


def test_delivery_recommendations_cover_common_ci_and_containers() -> None:
    from packs.software_delivery.project_profile.registry import recommendations_for_facet

    recs = recommendations_for_facet(default_detector_registry(), "delivery")
    assert ".github/workflows/*.yml" in recs
    assert ".gitlab-ci.yml" in recs
    assert "Jenkinsfile" in recs
    assert "Dockerfile" in recs
    assert "docker-compose.yml" in recs


def test_mixed_variant_is_ambiguous() -> None:
    profile = aggregate_profile(variant_evidence("mixed"), default_detector_registry())
    component = profile.components[0]
    assert component.facet_status["test_frameworks"] == "ambiguous"
    ids = {
        f.framework_id
        for f in component.facts
        if f.facet == "test_frameworks"
    }
    assert "robot_framework" in ids
    assert "pytest_bdd" in ids


def test_thin_variant_insufficient_context_with_recommendations() -> None:
    profile = aggregate_profile(variant_evidence("thin"), default_detector_registry())
    component = profile.components[0]
    assert component.facet_status.get("languages") == "insufficient_context"
    assert component.facet_status.get("test_frameworks") == "insufficient_context"
    assert any("pyproject.toml" in d or "package.json" in d for d in profile.diagnostics)
    assert component.facts == ()


def test_unrecognized_variant() -> None:
    profile = aggregate_profile(
        variant_evidence("unrecognized"), default_detector_registry()
    )
    component = profile.components[0]
    assert component.facet_status.get("test_frameworks") == "unrecognized"
    assert not any(f.facet == "test_frameworks" for f in component.facts)


def test_resource_layout_only_when_under_resources() -> None:
    from packs.software_delivery.project_profile.intake import ingest_profile_evidence

    evidence = ingest_profile_evidence(
        [
            {
                "files": [
                    {
                        "path": "robot/keywords/common.resource",
                        "content": "*** Keywords ***\nNoop\n    No Operation\n",
                    }
                ]
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    assert not any(c.name == "resource_layout" for c in profile.conventions)
    assert any(
        f.framework_id == "robot_framework"
        for f in profile.facts
        if f.facet == "test_frameworks"
    )


def test_gherkin_never_reported_as_cucumber() -> None:
    from packs.software_delivery.project_profile.intake import ingest_profile_evidence
    from packs.software_delivery.project_profile.registry import aggregate_profile as agg

    evidence = ingest_profile_evidence(
        [
            {
                "files": [
                    {
                        "path": "features/cancel.feature",
                        "content": "Feature: Cancel\n  Scenario: unpaid\n",
                    }
                ]
            }
        ]
    )
    profile = agg(evidence, default_detector_registry())
    syntax = [f for f in profile.facts if f.facet == "specification_syntaxes"]
    frameworks = [f for f in profile.facts if f.facet == "test_frameworks"]
    assert any(f.value == "gherkin" for f in syntax)
    assert all(f.value != "cucumber" and f.framework_id != "cucumber" for f in frameworks)
    assert all(f.value != "cucumber" for f in syntax)


def test_malformed_pyproject_does_not_invent_facts() -> None:
    from packs.software_delivery.project_profile.intake import ingest_profile_evidence

    evidence = ingest_profile_evidence(
        [{"files": [{"path": "pyproject.toml", "content": "[[[not valid"}]}]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    assert not any(f.facet == "languages" and f.value == "Python" for f in profile.facts)
    assert any("malformed" in d.lower() or "parse" in d.lower() for d in profile.diagnostics)


def test_requirements_txt_detects_python_language_and_dependencies() -> None:
    from packs.software_delivery.project_profile.intake import ingest_profile_evidence

    evidence = ingest_profile_evidence(
        [
            {
                "files": [
                    {
                        "path": "requirements.txt",
                        "content": (
                            "robotframework>=6.0\n"
                            "robotframework-seleniumlibrary>=6.0\n"
                            "pyyaml>=6.0\n"
                        ),
                    }
                ]
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert component.facet_status["languages"] == "detected"
    assert component.facet_status["build_and_dependencies"] == "detected"
    assert any(
        fact.facet == "languages" and fact.value == "Python" for fact in component.facts
    )
    assert any(
        fact.facet == "build_and_dependencies" and fact.value == "requirements_dependencies"
        for fact in component.facts
    )
    assert any(
        fact.framework_id == "robot_framework"
        for fact in component.facts
        if fact.facet == "test_frameworks"
    )
    assert not any(
        "insufficient_context for languages: provide requirements.txt" in diagnostic
        for diagnostic in profile.diagnostics
    )
    assert not any(
        "insufficient_context for build_and_dependencies: provide requirements.txt"
        in diagnostic
        for diagnostic in profile.diagnostics
    )
