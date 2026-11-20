"""Multi-framework matrix and pathological coverage (#429 slice 9)."""

from __future__ import annotations

from packs.software_delivery.project_profile.detectors import default_detector_registry
from packs.software_delivery.project_profile.fingerprint import profile_fingerprint
from packs.software_delivery.project_profile.intake import ingest_profile_evidence
from packs.software_delivery.project_profile.registry import aggregate_profile
from test.packs.software_delivery.project_profile.conftest import a0_evidence


def test_multi_component_isolation_no_project_ambiguous() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "py",
                "files": [
                    {
                        "path": "requirements.txt",
                        "content": "pytest==8.3.0\nselenium==4.15.0\n",
                    }
                ],
            },
            {
                "component": "js",
                "files": [
                    {
                        "path": "package.json",
                        "content": '{"devDependencies":{"cypress":"13.0.0"}}\n',
                    }
                ],
            },
            {
                "component": "java",
                "files": [
                    {
                        "path": "pom.xml",
                        "content": (
                            "<project xmlns=\"http://maven.apache.org/POM/4.0.0\">"
                            "<dependencies>"
                            "<dependency>"
                            "<groupId>io.cucumber</groupId>"
                            "<artifactId>cucumber-java</artifactId>"
                            "<version>7.14.0</version>"
                            "</dependency>"
                            "<dependency>"
                            "<groupId>org.junit.jupiter</groupId>"
                            "<artifactId>junit-jupiter</artifactId>"
                            "<version>5.10.0</version>"
                            "</dependency>"
                            "</dependencies>"
                            "</project>\n"
                        ),
                    }
                ],
            },
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    by_label = {c.label: c for c in profile.components}
    assert by_label["py"].facet_status["test_frameworks"] == "detected"
    assert by_label["js"].facet_status["test_frameworks"] == "detected"
    assert by_label["java"].facet_status["test_frameworks"] == "detected"
    assert profile.facet_status.get("test_frameworks") != "ambiguous"


def test_duplicate_evidence_dedupes_deterministically() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "tests",
                "files": [
                    {"path": "requirements.txt", "content": "pytest==8.3.0\n"},
                    {
                        "path": "pytest.ini",
                        "content": "[pytest]\ntestpaths = tests\n",
                    },
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    pytest_facts = [
        f
        for f in profile.components[0].facts
        if f.framework_id == "pytest"
    ]
    assert len(pytest_facts) == 1
    # Aggregator emits facts in sorted facet order, then by value within facet.
    assert [(f.facet, f.value) for f in profile.components[0].facts] == sorted(
        (f.facet, f.value) for f in profile.components[0].facts
    )
    assert any(
        f.facet == "languages" and f.value == "Python"
        for f in profile.components[0].facts
    )
    assert any(
        f.facet == "build_and_dependencies"
        and f.value == "requirements_dependencies"
        for f in profile.components[0].facts
    )


def test_a0_fingerprint_stable_with_extended_registry() -> None:
    evidence = a0_evidence()
    registry = default_detector_registry()
    a = aggregate_profile(evidence, registry)
    b = aggregate_profile(evidence, registry)
    assert a.profile_fingerprint == b.profile_fingerprint
    tuples = tuple(
        (c.label, f.path, f.content_hash)
        for c in evidence.components
        for f in c.files
    )
    assert a.profile_fingerprint == profile_fingerprint(
        tuples, registry.detector_tuples()
    )


def test_malformed_and_pathological_inputs() -> None:
    huge = "x" * 50_000
    evidence = ingest_profile_evidence(
        [
            {
                "component": "bad",
                "files": [
                    {"path": "package.json", "content": "{not json"},
                    {"path": "pom.xml", "content": "<project><unclosed>"},
                    {
                        "path": "requirements.txt",
                        "content": f"pytest==8.3.0\n# {huge}\n",
                    },
                    {"path": "e2e/blank.spec.ts", "content": ""},
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    assert any("malformed" in d for d in profile.diagnostics)
    pkg_diags = [
        d for d in profile.diagnostics if "malformed package.json" in d
    ]
    pom_diags = [d for d in profile.diagnostics if "malformed pom.xml" in d]
    assert len(pkg_diags) == 1
    assert len(pom_diags) == 1
    assert any("pathological line length" in d for d in profile.diagnostics)
    # Oversized requirements line is dropped by intake — no invented pytest fact.
    assert not any(
        f.framework_id == "pytest" for f in profile.components[0].facts
    )


def test_same_role_playwright_cypress_ambiguous() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "ui",
                "files": [
                    {
                        "path": "package.json",
                        "content": (
                            '{"devDependencies":{'
                            '"@playwright/test":"1.48.0",'
                            '"cypress":"13.0.0"'
                            "}}\n"
                        ),
                    }
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert {"playwright", "cypress"} <= {
        f.framework_id for f in component.facts if f.facet == "test_frameworks"
    }
    assert component.facet_status["test_frameworks"] == "ambiguous"
