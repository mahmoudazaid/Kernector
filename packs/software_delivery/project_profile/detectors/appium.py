"""Appium framework detection — evidence-gated, no device invention (#429)."""

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
_PY_EXACT = re.compile(
    r"""^Appium-Python-Client\s*(==|===)\s*(?P<version>[0-9][^;\s]*)""",
    re.IGNORECASE,
)


class AppiumDetector:
    detector_id = "appium"
    version = "1"
    facets = frozenset({"test_frameworks", "conventions"})
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "test_frameworks": (
            "requirements.txt",
            "package.json",
            "pom.xml",
            "build.gradle",
        ),
        "conventions": ("appium/", "**/capabilities*.json"),
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
                if "io.appium" in file.content or "appium" in file.content.lower():
                    if re.search(r"io\.appium|appium-java-client", file.content, re.I):
                        emissions.append(_appium_fact(component_label, file))
        return _dedupe(emissions)

    def _requirements(
        self, component: str, file: EvidenceFile
    ) -> list[DetectorEmission]:
        for line in file.content.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            if not lower.startswith("appium-python-client"):
                continue
            emissions = [_appium_fact(component, file)]
            exact = _PY_EXACT.match(stripped)
            if exact:
                emissions.append(
                    DetectorEmission(
                        convention=Convention(
                            name="framework_version",
                            value=f"appium=={exact.group('version')}",
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
        deps: dict[str, str] = {}
        for key in ("dependencies", "devDependencies"):
            block = data.get(key)
            if isinstance(block, dict):
                deps.update({str(k): str(v) for k, v in block.items()})
        if "appium" not in deps and "webdriverio" not in deps:
            return []
        # Require explicit appium package for framework claim.
        if "appium" not in deps:
            return []
        return [_appium_fact(component, file)]

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
            artifact = _text(dep, "artifactId")
            if group == "io.appium" or (
                artifact and "appium" in artifact.lower()
            ):
                return [_appium_fact(component, file)]
        return []


def _appium_fact(component: str, file: EvidenceFile) -> DetectorEmission:
    return DetectorEmission(
        fact=ProfileFact(
            facet="test_frameworks",
            value="appium",
            framework_id="appium",
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
        if emission.fact and emission.fact.framework_id == "appium":
            if seen:
                continue
            seen = True
        result.append(emission)
    return result
