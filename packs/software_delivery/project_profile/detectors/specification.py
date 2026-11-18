"""Specification syntax detection — never conflated with test frameworks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from packs.software_delivery.project_profile.detectors._refs import ref_for
from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import ProfileFact
from packs.software_delivery.project_profile.registry import DetectorEmission

_UNKNOWN_TEST_SUFFIXES = (".xyz", ".weird")


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
        saw_known_test = False
        saw_unknown = False
        for file in files:
            lower_name = file.path.rsplit("/", 1)[-1].lower()
            if file.path.endswith(".feature") or "Feature:" in file.content:
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
            if file.path.endswith((".robot", ".resource")) or lower_name in {
                "package.json",
                "requirements.txt",
                "pyproject.toml",
            }:
                # Presence of ordinary manifests/tests is handled by other detectors.
                if file.path.endswith((".robot", ".resource")):
                    saw_known_test = True
                if lower_name in {"package.json", "requirements.txt"}:
                    text = file.content.lower()
                    if any(
                        token in text
                        for token in (
                            "robotframework",
                            "playwright",
                            "pytest-bdd",
                            "pytest_bdd",
                            "cucumber",
                            "jest",
                        )
                    ):
                        saw_known_test = True
            if lower_name.endswith(_UNKNOWN_TEST_SUFFIXES) or lower_name.endswith(
                ".weird"
            ):
                saw_unknown = True
            if "totally-unknown-framework" in file.content.lower():
                saw_unknown = True

        if saw_unknown and not saw_known_test and not any(
            e.fact and e.fact.facet == "specification_syntaxes" for e in emissions
        ):
            # Only mark unrecognized when no other detector is likely to claim a framework.
            has_test_claim = any(
                f.path.endswith((".robot", ".resource"))
                or f.path.rsplit("/", 1)[-1] in {"package.json", "requirements.txt"}
                for f in files
            )
            if not has_test_claim or saw_unknown:
                emissions.append(
                    DetectorEmission(
                        unrecognized_facet="test_frameworks",
                        diagnostic="unrecognized test framework evidence present",
                    )
                )
        return emissions
