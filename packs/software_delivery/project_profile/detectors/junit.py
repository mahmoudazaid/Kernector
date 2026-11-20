"""JUnit runner detection from Maven/Gradle evidence (#429)."""

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
_JUNIT_ARTIFACTS = frozenset(
    {
        "junit",
        "junit-jupiter",
        "junit-jupiter-api",
        "junit-jupiter-engine",
        "junit-platform-suite",
    }
)
# Content must show JUnit usage; path alone (e.g. TestNG under src/test/java/)
# must not claim suite ownership.
_JUNIT_USAGE = re.compile(
    r"\borg\.junit\b|@org\.junit\b|"
    r"import\s+org\.junit(?:\.\w+)*\s*;|"
    r"import\s+static\s+org\.junit(?:\.\w+)*\.",
    re.IGNORECASE,
)


class JUnitDetector:
    detector_id = "junit"
    version = "1"
    facets = frozenset({"test_frameworks", "conventions"})
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "test_frameworks": ("pom.xml", "build.gradle", "build.gradle.kts"),
        "conventions": ("src/test/java/", "src/test/kotlin/"),
    }

    def detect(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        # Ownership only from files that both live under a Java/Kotlin test root
        # and show JUnit usage — path alone is shared with TestNG.
        junit_sources = [
            f
            for f in files
            if (
                f.path.startswith("src/test/java/")
                or f.path.startswith("src/test/kotlin/")
            )
            and _JUNIT_USAGE.search(f.content)
        ]
        if any(f.path.startswith("src/test/java/") for f in junit_sources):
            ownership = "src/test/java/"
        elif any(f.path.startswith("src/test/kotlin/") for f in junit_sources):
            ownership = "src/test/kotlin/"
        else:
            ownership = None
        for file in files:
            name = file.path.rsplit("/", 1)[-1]
            if name == "pom.xml":
                emissions.extend(self._pom(component_label, file, ownership))
            elif name in {"build.gradle", "build.gradle.kts"}:
                emissions.extend(self._gradle(component_label, file, ownership))
        if ownership and junit_sources and any(
            e.fact and e.fact.framework_id == "junit" for e in emissions
        ):
            emissions.append(
                DetectorEmission(
                    convention=Convention(
                        name="test_root",
                        value=ownership,
                        evidence_refs=(ref_for(component_label, junit_sources[0]),),
                    )
                )
            )
        return _dedupe_runner(emissions, "junit")

    def _pom(
        self,
        component: str,
        file: EvidenceFile,
        ownership: str | None,
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
            group = _text(dep, "groupId")
            if artifact not in _JUNIT_ARTIFACTS and not (
                group and group.startswith("org.junit")
            ):
                continue
            emissions = [
                DetectorEmission(
                    fact=ProfileFact(
                        facet="test_frameworks",
                        value="junit",
                        framework_id="junit",
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
                            value=f"junit=={version}",
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
        ownership: str | None,
    ) -> list[DetectorEmission]:
        for line in file.content.splitlines():
            lower = line.lower()
            if "junit" not in lower:
                continue
            if any(
                token in lower
                for token in ("junit-jupiter", "junit:", "org.junit", '"junit"', "'junit'")
            ):
                return [
                    DetectorEmission(
                        fact=ProfileFact(
                            facet="test_frameworks",
                            value="junit",
                            framework_id="junit",
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


def _dedupe_runner(
    emissions: list[DetectorEmission], framework_id: str
) -> list[DetectorEmission]:
    seen = False
    result: list[DetectorEmission] = []
    for emission in emissions:
        if emission.fact and emission.fact.framework_id == framework_id:
            if seen:
                continue
            seen = True
        result.append(emission)
    return result
