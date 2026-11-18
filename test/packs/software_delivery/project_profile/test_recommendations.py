"""Detector-declared insufficient-evidence recommendations (#387)."""

from __future__ import annotations

from packs.software_delivery.project_profile.detectors import default_detector_registry
from packs.software_delivery.project_profile.registry import (
    TechnologyDetectorRegistry,
    recommendations_for_facet,
)


def test_recommendations_come_from_registered_detectors_not_a_central_map() -> None:
    registry = default_detector_registry()
    test_recs = recommendations_for_facet(registry, "test_frameworks")
    assert "requirements.txt" in test_recs
    assert "package.json" in test_recs
    assert "**/*.robot" in test_recs
    assert "**/*.spec.ts" in test_recs
    assert "**/*.spec.js" in test_recs

    reusable_recs = recommendations_for_facet(registry, "reusable_components")
    assert "resources/*.resource" in reusable_recs
    assert "components/**/*.ts" in reusable_recs
    assert "e2e/**/*.ts" in reusable_recs


def test_recommendations_follow_whichever_detectors_are_registered() -> None:
    class OnlyPython:
        detector_id = "only_python"
        version = "1"
        facets = frozenset({"languages"})
        evidence_recommendations = {
            "languages": ("Cargo.toml",),
        }

        def detect(self, component_label: str, files: tuple):
            return []

    registry = TechnologyDetectorRegistry((OnlyPython(),))
    assert recommendations_for_facet(registry, "languages") == ("Cargo.toml",)
    assert recommendations_for_facet(registry, "test_frameworks") == ()
