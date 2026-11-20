"""Pytest runner detection from manifests and config (#429)."""

from __future__ import annotations

import configparser
import re
import tomllib
from collections.abc import Mapping
from typing import ClassVar

from packs.software_delivery.project_profile.detectors._refs import ref_for
from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import Convention, ProfileFact
from packs.software_delivery.project_profile.registry import DetectorEmission

_EXACT_PIN = re.compile(
    r"""^pytest\s*(==|===)\s*(?P<version>[0-9][^;\s]*)""",
    re.IGNORECASE,
)


class PytestFrameworkDetector:
    detector_id = "pytest_framework"
    version = "1"
    facets = frozenset({"test_frameworks", "conventions", "reusable_components"})
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "test_frameworks": (
            "requirements.txt",
            "pyproject.toml",
            "pytest.ini",
            "setup.cfg",
            "conftest.py",
        ),
        "conventions": ("pytest.ini", "pyproject.toml", "tests/"),
        "reusable_components": ("**/conftest.py",),
    }

    def detect(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        for file in files:
            name = file.path.rsplit("/", 1)[-1]
            if name == "requirements.txt":
                emissions.extend(self._requirements(component_label, file))
            elif name == "pyproject.toml":
                emissions.extend(self._pyproject(component_label, file))
            elif name == "pytest.ini":
                emissions.extend(self._pytest_ini(component_label, file))
            elif name == "setup.cfg":
                emissions.extend(self._setup_cfg(component_label, file))
        return _dedupe_pytest_facts(emissions)

    def _requirements(
        self, component: str, file: EvidenceFile
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        for line in file.content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lower = stripped.lower()
            if not lower.startswith("pytest") or lower.startswith("pytest-"):
                continue
            emissions.append(_pytest_fact(component, file))
            exact = _EXACT_PIN.match(stripped)
            if exact:
                emissions.append(
                    DetectorEmission(
                        convention=Convention(
                            name="framework_version",
                            value=f"pytest=={exact.group('version')}",
                            evidence_refs=(ref_for(component, file),),
                        )
                    )
                )
            break
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
        emissions: list[DetectorEmission] = []
        if _pyproject_mentions_pytest(data):
            emissions.append(_pytest_fact(component, file))
            version = _exact_pyproject_pytest_version(data)
            if version:
                emissions.append(
                    DetectorEmission(
                        convention=Convention(
                            name="framework_version",
                            value=f"pytest=={version}",
                            evidence_refs=(ref_for(component, file),),
                        )
                    )
                )
        tool = data.get("tool")
        if isinstance(tool, dict) and isinstance(tool.get("pytest"), dict):
            emissions.append(_pytest_fact(component, file))
            ini = tool["pytest"].get("ini_options")
            if isinstance(ini, dict) and "testpaths" in ini:
                paths = ini["testpaths"]
                value = (
                    paths[0]
                    if isinstance(paths, list) and paths
                    else str(paths)
                )
                emissions.append(
                    DetectorEmission(
                        convention=Convention(
                            name="test_root",
                            value=str(value).rstrip("/") + "/",
                            evidence_refs=(ref_for(component, file),),
                        )
                    )
                )
        return emissions

    def _pytest_ini(
        self, component: str, file: EvidenceFile
    ) -> list[DetectorEmission]:
        emissions = [_pytest_fact(component, file)]
        parser = configparser.ConfigParser()
        try:
            parser.read_string(file.content)
        except configparser.Error:
            return [
                DetectorEmission(
                    diagnostic=f"malformed pytest.ini could not be parsed: {file.path}"
                ),
                _pytest_fact(component, file),
            ]
        if parser.has_option("pytest", "testpaths"):
            value = parser.get("pytest", "testpaths").split()[0]
            emissions.append(
                DetectorEmission(
                    convention=Convention(
                        name="test_root",
                        value=value.rstrip("/") + "/",
                        evidence_refs=(ref_for(component, file),),
                    )
                )
            )
        return emissions

    def _setup_cfg(
        self, component: str, file: EvidenceFile
    ) -> list[DetectorEmission]:
        lower = file.content.lower()
        if "[tool:pytest]" in lower or "[pytest]" in lower:
            return [_pytest_fact(component, file)]
        return []


def _pytest_fact(component: str, file: EvidenceFile) -> DetectorEmission:
    return DetectorEmission(
        fact=ProfileFact(
            facet="test_frameworks",
            value="pytest",
            framework_id="pytest",
            confidence="high",
            evidence_refs=(ref_for(component, file),),
        ),
        role="runner",
    )


def _pyproject_mentions_pytest(data: dict) -> bool:
    project = data.get("project")
    if not isinstance(project, dict):
        return False
    for key in ("dependencies", "optional-dependencies"):
        block = project.get(key)
        if isinstance(block, list):
            for item in block:
                if _is_pytest_requirement(item):
                    return True
        if isinstance(block, dict):
            for values in block.values():
                if isinstance(values, list):
                    for item in values:
                        if _is_pytest_requirement(item):
                            return True
    return False


def _exact_pyproject_pytest_version(data: dict) -> str | None:
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    for key in ("dependencies", "optional-dependencies"):
        block = project.get(key)
        candidates: list[str] = []
        if isinstance(block, list):
            candidates.extend(str(item) for item in block)
        elif isinstance(block, dict):
            for values in block.values():
                if isinstance(values, list):
                    candidates.extend(str(item) for item in values)
        for item in candidates:
            match = _EXACT_PIN.match(item.strip())
            if match:
                return match.group("version")
    return None


def _is_pytest_requirement(item: object) -> bool:
    if not isinstance(item, str):
        return False
    lower = item.strip().lower()
    return lower.startswith("pytest") and not lower.startswith("pytest-")


def _dedupe_pytest_facts(
    emissions: list[DetectorEmission],
) -> list[DetectorEmission]:
    seen_fact = False
    result: list[DetectorEmission] = []
    for emission in emissions:
        if emission.fact and emission.fact.framework_id == "pytest":
            if seen_fact:
                continue
            seen_fact = True
        result.append(emission)
    return result
