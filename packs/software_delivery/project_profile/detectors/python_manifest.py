"""Python language and dependency detection from pyproject.toml / requirements."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from typing import ClassVar

from packs.software_delivery.project_profile.detectors._refs import ref_for
from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import ProfileFact
from packs.software_delivery.project_profile.registry import DetectorEmission


class PythonManifestDetector:
    detector_id = "python_manifest"
    version = "1"
    facets = frozenset({"languages", "build_and_dependencies", "test_frameworks"})
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "languages": ("pyproject.toml", "requirements.txt", "setup.cfg", "Pipfile"),
        "build_and_dependencies": ("pyproject.toml", "requirements.txt", "Pipfile"),
        "test_frameworks": ("requirements.txt", "pyproject.toml", "**/*.robot"),
    }

    def detect(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        for file in files:
            name = file.path.rsplit("/", 1)[-1]
            if name == "pyproject.toml":
                emissions.extend(self._pyproject(component_label, file))
            elif name == "requirements.txt":
                emissions.extend(self._requirements(component_label, file))
        return emissions

    def _pyproject(
        self, component: str, file: EvidenceFile
    ) -> list[DetectorEmission]:
        try:
            data = tomllib.loads(file.content)
        except tomllib.TOMLDecodeError:
            return [
                DetectorEmission(
                    diagnostic=f"malformed pyproject.toml could not be parsed: {file.path}"
                )
            ]
        emissions: list[DetectorEmission] = [
            DetectorEmission(
                fact=ProfileFact(
                    facet="languages",
                    value="Python",
                    language="Python",
                    confidence="high",
                    evidence_refs=(ref_for(component, file),),
                )
            )
        ]
        project = data.get("project")
        if isinstance(project, dict):
            deps = project.get("dependencies")
            if isinstance(deps, list) and deps:
                emissions.append(
                    DetectorEmission(
                        fact=ProfileFact(
                            facet="build_and_dependencies",
                            value="pyproject_dependencies",
                            confidence="high",
                            evidence_refs=(ref_for(component, file),),
                        )
                    )
                )
        return emissions

    def _requirements(
        self, component: str, file: EvidenceFile
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        lower = file.content.lower()
        if "robotframework" in lower:
            emissions.append(
                DetectorEmission(
                    fact=ProfileFact(
                        facet="test_frameworks",
                        value="robot_framework",
                        framework_id="robot_framework",
                        confidence="high",
                        evidence_refs=(ref_for(component, file),),
                    ),
                    role="framework",
                )
            )
        if "pytest-bdd" in lower or "pytest_bdd" in lower:
            emissions.append(
                DetectorEmission(
                    fact=ProfileFact(
                        facet="test_frameworks",
                        value="pytest_bdd",
                        framework_id="pytest_bdd",
                        confidence="high",
                        evidence_refs=(ref_for(component, file),),
                    ),
                    role="framework",
                )
            )
        return emissions
