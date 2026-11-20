"""Pytest runner detection (#429 slice 2)."""

from __future__ import annotations

from packs.software_delivery.project_profile.detectors import default_detector_registry
from packs.software_delivery.project_profile.extractors.pytest_fixtures import (
    PytestFixtureExtractor,
)
from packs.software_delivery.project_profile.intake import ingest_profile_evidence
from packs.software_delivery.project_profile.registry import aggregate_profile
from packs.software_delivery.project_profile.reusable import collect_reusable_components


def test_pytest_from_requirements_exact_version() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "tests",
                "files": [
                    {"path": "requirements.txt", "content": "pytest==8.3.0\n"}
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert any(f.framework_id == "pytest" for f in component.facts)
    assert any(
        c.name == "framework_version" and c.value == "pytest==8.3.0"
        for c in component.conventions
    )
    assert component.facet_status["test_frameworks"] == "detected"


def test_pytest_range_omits_version() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "tests",
                "files": [{"path": "requirements.txt", "content": "pytest>=8.0\n"}],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert any(f.framework_id == "pytest" for f in component.facts)
    assert not any(c.name == "framework_version" for c in component.conventions)


def test_pytest_ini_and_tool_pytest_config() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "tests",
                "files": [
                    {
                        "path": "pytest.ini",
                        "content": "[pytest]\ntestpaths = tests\n",
                    }
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert any(f.framework_id == "pytest" for f in component.facts)
    assert any(c.name == "test_root" and c.value == "tests/" for c in component.conventions)


def test_pytest_and_pytest_bdd_coexist_as_detected() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "tests",
                "files": [
                    {
                        "path": "requirements.txt",
                        "content": "pytest==8.3.0\npytest-bdd==7.1.0\n",
                    }
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    ids = {
        f.framework_id
        for f in component.facts
        if f.facet == "test_frameworks"
    }
    assert ids == {"pytest", "pytest_bdd"}
    assert component.facet_status["test_frameworks"] == "detected"


def test_conftest_fixtures_require_decorator() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "tests",
                "files": [
                    {
                        "path": "conftest.py",
                        "content": (
                            "import pytest\n"
                            "@pytest.fixture\n"
                            "def client():\n"
                            "    return object()\n"
                        ),
                    },
                    {
                        "path": "tests/conftest.py",
                        "content": "# empty helper module\n",
                    },
                ],
            }
        ]
    )
    components, diagnostics = collect_reusable_components(
        evidence, extractors=(PytestFixtureExtractor(),), return_diagnostics=True
    )
    assert len(components) == 1
    assert components[0].kind == "fixture"
    assert components[0].signature == "client"
    assert any("insufficient" in d.lower() for d in diagnostics)


def test_malformed_pyproject_for_pytest_yields_diagnostic() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "tests",
                "files": [{"path": "pyproject.toml", "content": "[[broken\n"}],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    assert any("malformed pyproject" in d for d in profile.diagnostics)


def test_gherkin_not_implied_by_pytest() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "tests",
                "files": [{"path": "requirements.txt", "content": "pytest==8.3.0\n"}],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert not any(f.facet == "specification_syntaxes" for f in component.facts)
