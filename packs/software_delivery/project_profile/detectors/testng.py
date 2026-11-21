"""TestNG runner detection (#429)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from itertools import chain
from typing import ClassVar

from packs.software_delivery.project_profile.detectors._refs import ref_for
from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import Convention, ProfileFact
from packs.software_delivery.project_profile.registry import DetectorEmission

_NS = {"m": "http://maven.apache.org/POM/4.0.0"}


class TestNGDetector:
    detector_id = "testng"
    version = "1"
    facets = frozenset({"test_frameworks", "conventions"})
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "test_frameworks": (
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "testng.xml",
            "**/testng*.xml",
        ),
        "conventions": ("testng.xml", "src/test/"),
    }

    def detect(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        suite_files = [
            f
            for f in files
            if f.path.rsplit("/", 1)[-1].startswith("testng")
            and f.path.endswith(".xml")
        ]
        for file in files:
            name = file.path.rsplit("/", 1)[-1]
            if name == "pom.xml":
                emissions.extend(self._pom(component_label, file, suite_files))
            elif name in {"build.gradle", "build.gradle.kts"}:
                emissions.extend(self._gradle(component_label, file, suite_files))
        for suite in suite_files:
            if not any(e.fact and e.fact.framework_id == "testng" for e in emissions):
                emissions.append(
                    DetectorEmission(
                        fact=ProfileFact(
                            facet="test_frameworks",
                            value="testng",
                            framework_id="testng",
                            confidence="high",
                            evidence_refs=(ref_for(component_label, suite),),
                        ),
                        role="runner",
                        suite_ownership_key=suite.path,
                    )
                )
            emissions.append(
                DetectorEmission(
                    convention=Convention(
                        name="test_root",
                        value=suite.path,
                        evidence_refs=(ref_for(component_label, suite),),
                    )
                )
            )
        return _dedupe(emissions)

    def _pom(
        self,
        component: str,
        file: EvidenceFile,
        suite_files: list[EvidenceFile],
    ) -> list[DetectorEmission]:
        try:
            root = ET.fromstring(file.content)
        except ET.ParseError:
            return [
                DetectorEmission(
                    diagnostic=f"malformed pom.xml could not be parsed: {file.path}"
                )
            ]
        for dep in chain(
            root.findall(".//m:dependency", _NS),
            root.findall(".//dependency"),
        ):
            artifact = _text(dep, "artifactId")
            if artifact != "testng":
                continue
            # Dep-only without suite XML keeps ownership unset so unresolved
            # competition with JUnit stays ambiguous.
            ownership = suite_files[0].path if suite_files else None
            emissions = [
                DetectorEmission(
                    fact=ProfileFact(
                        facet="test_frameworks",
                        value="testng",
                        framework_id="testng",
                        confidence="high",
                        evidence_refs=(ref_for(component, file),),
                    ),
                    role="runner",
                    suite_ownership_key=ownership,
                )
            ]
            version = _text(dep, "version")
            if version and not version.startswith("${") and re.match(
                r"^\d+(\.\d+)*", version
            ):
                emissions.append(
                    DetectorEmission(
                        convention=Convention(
                            name="framework_version",
                            value=f"testng=={version}",
                            evidence_refs=(ref_for(component, file),),
                        )
                    )
                )
            return emissions
        return []

    def _gradle(
        self,
        component: str,
        file: EvidenceFile,
        suite_files: list[EvidenceFile],
    ) -> list[DetectorEmission]:
        for line in file.content.splitlines():
            if "testng" in line.lower():
                ownership = (
                    suite_files[0].path if suite_files else None
                )
                return [
                    DetectorEmission(
                        fact=ProfileFact(
                            facet="test_frameworks",
                            value="testng",
                            framework_id="testng",
                            confidence="high",
                            evidence_refs=(ref_for(component, file),),
                        ),
                        role="runner",
                        suite_ownership_key=ownership,
                    )
                ]
        return []


def _text(node: ET.Element, tag: str) -> str | None:
    child = node.find(f"m:{tag}", _NS)
    if child is None:
        child = node.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _dedupe(emissions: list[DetectorEmission]) -> list[DetectorEmission]:
    seen = False
    result: list[DetectorEmission] = []
    for emission in emissions:
        if emission.fact and emission.fact.framework_id == "testng":
            if seen:
                continue
            seen = True
        result.append(emission)
    return result
