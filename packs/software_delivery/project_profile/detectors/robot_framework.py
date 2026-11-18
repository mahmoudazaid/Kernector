"""Robot Framework detection and test conventions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from packs.software_delivery.project_profile.detectors._refs import ref_for
from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import Convention, ProfileFact
from packs.software_delivery.project_profile.registry import DetectorEmission


class RobotFrameworkDetector:
    detector_id = "robot_framework"
    version = "1"
    facets = frozenset({"test_frameworks", "conventions", "reusable_components"})
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "test_frameworks": ("**/*.robot", "resources/*.resource"),
        "conventions": ("tests/", "resources/"),
        "reusable_components": ("resources/*.resource", "**/*.robot"),
    }

    def detect(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        robot_files = [f for f in files if f.path.endswith(".robot")]
        resource_files = [f for f in files if f.path.endswith(".resource")]
        if not robot_files and not resource_files:
            return emissions

        evidence_file = robot_files[0] if robot_files else resource_files[0]
        emissions.append(
            DetectorEmission(
                fact=ProfileFact(
                    facet="test_frameworks",
                    value="robot_framework",
                    framework_id="robot_framework",
                    confidence="high",
                    evidence_refs=(ref_for(component_label, evidence_file),),
                )
            )
        )
        test_roots = sorted(
            {
                "/".join(f.path.split("/")[:2])
                if f.path.startswith("tests/")
                else "tests"
                for f in robot_files
                if f.path.startswith("tests/")
            }
        )
        if test_roots:
            emissions.append(
                DetectorEmission(
                    convention=Convention(
                        name="test_root",
                        value="tests/",
                        evidence_refs=(ref_for(component_label, robot_files[0]),),
                    )
                )
            )
        if resource_files:
            emissions.append(
                DetectorEmission(
                    convention=Convention(
                        name="resource_layout",
                        value="resources/",
                        evidence_refs=(ref_for(component_label, resource_files[0]),),
                    )
                )
            )
        return emissions
