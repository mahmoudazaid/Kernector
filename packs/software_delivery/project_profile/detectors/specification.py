"""Specification syntax detection — never conflated with test frameworks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from packs.software_delivery.project_profile.detectors._refs import ref_for
from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import ProfileFact
from packs.software_delivery.project_profile.registry import DetectorEmission

# Path segments that indicate test-shaped evidence without naming a framework.
_TEST_DIR_SEGMENTS = frozenset(
    {"tests", "test", "__tests__", "e2e", "spec", "cypress"}
)
_TEST_NAME_MARKERS = (".test.", ".spec.", ".cy.")
# Extensions / basenames other MVP detectors already claim for test_frameworks.
_KNOWN_TEST_SUFFIXES = (".robot", ".resource")
_KNOWN_TEST_BASENAMES = frozenset({"package.json", "requirements.txt", "pyproject.toml"})
# Paths NodePackageDetector already recommends / can claim via package.json.
# Without a detecting fact these should stay insufficient_context, not unrecognized.
_NODE_OWNED_NAME_MARKERS = (".spec.", ".test.")
_NODE_OWNED_DIR_SEGMENTS = frozenset({"e2e"})


class SpecificationSyntaxDetector:
    detector_id = "specification_syntax"
    version = "1"
    facets = frozenset({"specification_syntaxes", "test_frameworks"})
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "specification_syntaxes": ("**/*.feature",),
        "test_frameworks": (),
    }

    def detect(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        saw_unrecognized = False
        for file in files:
            lower_name = file.path.rsplit("/", 1)[-1].lower()
            if file.path.endswith(".feature"):
                emissions.append(
                    DetectorEmission(
                        fact=ProfileFact(
                            facet="specification_syntaxes",
                            value="gherkin",
                            confidence="high",
                            evidence_refs=(ref_for(component_label, file),),
                        )
                    )
                )
            if (
                _looks_like_test_evidence(file.path)
                and not _known_test_claim(file.path, lower_name)
                and not _node_owned_test_path(file.path)
            ):
                saw_unrecognized = True

        if saw_unrecognized:
            emissions.append(
                DetectorEmission(
                    unrecognized_facet="test_frameworks",
                    diagnostic="unrecognized test framework evidence present",
                )
            )
        return emissions


def _looks_like_test_evidence(path: str) -> bool:
    parts = path.split("/")
    if any(part in _TEST_DIR_SEGMENTS for part in parts[:-1]):
        return True
    name = parts[-1].lower()
    if any(marker in name for marker in _TEST_NAME_MARKERS):
        return True
    return name.endswith("test.java") or name.endswith("tests.java")


def _known_test_claim(path: str, lower_name: str) -> bool:
    if path.endswith(_KNOWN_TEST_SUFFIXES):
        return True
    return lower_name in _KNOWN_TEST_BASENAMES


def _node_owned_test_path(path: str) -> bool:
    parts = path.split("/")
    if any(part in _NODE_OWNED_DIR_SEGMENTS for part in parts[:-1]):
        return True
    name = parts[-1].lower()
    return any(marker in name for marker in _NODE_OWNED_NAME_MARKERS)
