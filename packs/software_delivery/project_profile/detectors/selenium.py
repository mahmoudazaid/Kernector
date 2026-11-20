"""Selenium library detection across Python/JS/Java manifests (#429)."""

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

_PY_EXACT = re.compile(
    r"""^selenium\s*(==|===)\s*(?P<version>[0-9][^;\s]*)""",
    re.IGNORECASE,
)
_EXACT_NPM = re.compile(r"^(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$")
_NS = {"m": "http://maven.apache.org/POM/4.0.0"}


class SeleniumDetector:
    detector_id = "selenium"
    version = "1"
    facets = frozenset({"test_frameworks", "conventions", "reusable_components"})
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "test_frameworks": (
            "requirements.txt",
            "package.json",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
        ),
        "conventions": ("tests/", "src/test/"),
        "reusable_components": ("**/pages/**", "**/pageobjects/**"),
    }

    def detect(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        for file in files:
            name = file.path.rsplit("/", 1)[-1]
            if name == "requirements.txt":
                emissions.extend(self._requirements(component_label, file))
            elif name == "package.json":
                emissions.extend(self._package_json(component_label, file))
            elif name == "pom.xml":
                emissions.extend(self._pom(component_label, file))
            elif name in {"build.gradle", "build.gradle.kts"}:
                emissions.extend(self._gradle(component_label, file))
        return _dedupe_selenium(emissions)

    def _requirements(
        self, component: str, file: EvidenceFile
    ) -> list[DetectorEmission]:
        for line in file.content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lower = stripped.lower()
            if not lower.startswith("selenium"):
                continue
            emissions = [_selenium_fact(component, file)]
            exact = _PY_EXACT.match(stripped)
            if exact:
                emissions.append(
                    DetectorEmission(
                        convention=Convention(
                            name="framework_version",
                            value=f"selenium=={exact.group('version')}",
                            evidence_refs=(ref_for(component, file),),
                        )
                    )
                )
            return emissions
        return []

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
        deps = {}
        for key in ("dependencies", "devDependencies"):
            block = data.get(key)
            if isinstance(block, dict):
                deps.update({str(k): str(v) for k, v in block.items()})
        # Direct selenium-webdriver only; ignore transitive mentions elsewhere.
        if "selenium-webdriver" not in deps:
            return []
        emissions = [_selenium_fact(component, file)]
        raw = deps["selenium-webdriver"].lstrip("v=")
        if _EXACT_NPM.match(raw) and not any(
            m in deps["selenium-webdriver"] for m in ("^", "~", ">", "<", "*")
        ):
            emissions.append(
                DetectorEmission(
                    convention=Convention(
                        name="framework_version",
                        value=f"selenium=={raw}",
                        evidence_refs=(ref_for(component, file),),
                    )
                )
            )
        return emissions

    def _pom(self, component: str, file: EvidenceFile) -> list[DetectorEmission]:
        try:
            root = ET.fromstring(file.content)
        except ET.ParseError:
            return [
                DetectorEmission(
                    diagnostic=f"malformed pom.xml could not be parsed: {file.path}"
                )
            ]
        for dep in root.findall(".//m:dependency", _NS) or root.findall(".//dependency"):
            group = _text(dep, "groupId")
            artifact = _text(dep, "artifactId")
            if group == "org.seleniumhq.selenium" and artifact and "selenium" in artifact:
                emissions = [_selenium_fact(component, file)]
                version = _text(dep, "version")
                if version and not version.startswith("${") and re.match(
                    r"^\d+\.\d+", version
                ):
                    emissions.append(
                        DetectorEmission(
                            convention=Convention(
                                name="framework_version",
                                value=f"selenium=={version}",
                                evidence_refs=(ref_for(component, file),),
                            )
                        )
                    )
                return emissions
        return []

    def _gradle(
        self, component: str, file: EvidenceFile
    ) -> list[DetectorEmission]:
        for line in file.content.splitlines():
            if "org.seleniumhq.selenium" in line or "selenium-java" in line:
                if ":" in line or '"' in line or "'" in line:
                    return [_selenium_fact(component, file)]
        return []


def _selenium_fact(component: str, file: EvidenceFile) -> DetectorEmission:
    return DetectorEmission(
        fact=ProfileFact(
            facet="test_frameworks",
            value="selenium",
            framework_id="selenium",
            confidence="high",
            evidence_refs=(ref_for(component, file),),
        ),
        role="library",
    )


def _text(node: ET.Element, tag: str) -> str | None:
    child = node.find(f"m:{tag}", _NS)
    if child is None:
        child = node.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _dedupe_selenium(emissions: list[DetectorEmission]) -> list[DetectorEmission]:
    seen = False
    result: list[DetectorEmission] = []
    for emission in emissions:
        if emission.fact and emission.fact.framework_id == "selenium":
            if seen:
                continue
            seen = True
        result.append(emission)
    return result
