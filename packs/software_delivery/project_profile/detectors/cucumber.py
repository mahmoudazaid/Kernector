"""Cucumber framework detection — does not extract step definitions (#429)."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from typing import ClassVar

from packs.software_delivery.project_profile.detectors._refs import ref_for
from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import Convention, ProfileFact
from packs.software_delivery.project_profile.registry import DetectorEmission

_NS = {"m": "http://maven.apache.org/POM/4.0.0"}


class CucumberDetector:
    detector_id = "cucumber"
    version = "1"
    facets = frozenset({"test_frameworks", "conventions"})
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "test_frameworks": (
            "package.json",
            "pom.xml",
            "build.gradle",
            "requirements.txt",
            "cucumber.js",
            "cucumber.yml",
        ),
        "conventions": ("features/", "**/steps/", "**/step_definitions/"),
    }

    def detect(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        for file in files:
            name = file.path.rsplit("/", 1)[-1]
            if name == "package.json":
                emissions.extend(self._package_json(component_label, file))
            elif name == "pom.xml":
                emissions.extend(self._pom(component_label, file))
            elif name in {"build.gradle", "build.gradle.kts"}:
                if re.search(r"io\.cucumber|cucumber-java|cucumber-junit", file.content):
                    emissions.append(_cucumber_fact(component_label, file))
            elif name == "requirements.txt":
                emissions.extend(self._requirements(component_label, file))
            elif name in {"cucumber.js", "cucumber.json", "cucumber.yaml", "cucumber.yml"}:
                emissions.append(_cucumber_fact(component_label, file))
            elif name.endswith(".feature"):
                # Glue path convention only — Gherkin syntax owned by specification detector.
                if "/steps/" in f"/{file.path}" or "step_definitions" in file.path:
                    continue
        glue = [
            f
            for f in files
            if "step_definitions" in f.path
            or f.path.startswith("features/steps/")
            or "/steps/" in f"/{f.path}"
        ]
        if glue and any(e.fact and e.fact.framework_id == "cucumber" for e in emissions):
            emissions.append(
                DetectorEmission(
                    convention=Convention(
                        name="glue_path",
                        value=glue[0].path.rsplit("/", 1)[0] + "/",
                        evidence_refs=(ref_for(component_label, glue[0]),),
                    )
                )
            )
        return _dedupe(emissions)

    def _package_json(
        self, component: str, file: EvidenceFile
    ) -> list[DetectorEmission]:
        try:
            data = json.loads(file.content)
        except json.JSONDecodeError:
            return [
                DetectorEmission(
                    diagnostic=f"malformed package.json could not be parsed: {file.path}"
                )
            ]
        if not isinstance(data, dict):
            return []
        deps: set[str] = set()
        for key in ("dependencies", "devDependencies"):
            block = data.get(key)
            if isinstance(block, dict):
                deps.update(str(k) for k in block)
        if "@cucumber/cucumber" in deps or "cucumber" in deps:
            return [_cucumber_fact(component, file)]
        return []

    def _pom(
        self, component: str, file: EvidenceFile
    ) -> list[DetectorEmission]:
        try:
            root = ET.fromstring(file.content)
        except ET.ParseError:
            return [
                DetectorEmission(
                    diagnostic=f"malformed pom.xml could not be parsed: {file.path}"
                )
            ]
        for dep in list(root.findall(".//m:dependency", _NS)) + list(
            root.findall(".//dependency")
        ):
            group = _text(dep, "groupId")
            artifact = _text(dep, "artifactId") or ""
            if group == "io.cucumber" or artifact.startswith("cucumber-"):
                return [_cucumber_fact(component, file)]
        return []

    def _requirements(
        self, component: str, file: EvidenceFile
    ) -> list[DetectorEmission]:
        # Python cucumber packages are uncommon; do not treat pytest-bdd as cucumber.
        for line in file.content.splitlines():
            stripped = line.strip().lower()
            if stripped.startswith("cucumber") and not stripped.startswith(
                "cucumber-expressions"
            ):
                return [_cucumber_fact(component, file)]
        return []


def _cucumber_fact(component: str, file: EvidenceFile) -> DetectorEmission:
    return DetectorEmission(
        fact=ProfileFact(
            facet="test_frameworks",
            value="cucumber",
            framework_id="cucumber",
            confidence="high",
            evidence_refs=(ref_for(component, file),),
        ),
        role="framework",
    )


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
        if emission.fact and emission.fact.framework_id == "cucumber":
            if seen:
                continue
            seen = True
        result.append(emission)
    return result
