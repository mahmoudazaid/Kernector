"""Cypress framework detection (#429)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import ClassVar

from packs.software_delivery.project_profile.detectors._refs import ref_for
from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import Convention, ProfileFact
from packs.software_delivery.project_profile.registry import DetectorEmission

_CONFIG_NAMES = frozenset(
    {
        "cypress.config.ts",
        "cypress.config.js",
        "cypress.config.mjs",
        "cypress.config.cjs",
    }
)
_EXACT_VERSION = re.compile(r"^(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$")


class CypressDetector:
    detector_id = "cypress"
    version = "1"
    facets = frozenset({"test_frameworks", "conventions", "reusable_components"})
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "test_frameworks": (
            "cypress.config.ts",
            "cypress.config.js",
            "package.json",
            "cypress/**/*.ts",
            "cypress/**/*.js",
        ),
        "conventions": ("cypress/", "cypress.config.ts", "cypress.config.js"),
        "reusable_components": (
            "cypress/support/**/*.ts",
            "cypress/support/**/*.js",
            "cypress/fixtures/**",
        ),
    }

    def detect(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        package = next(
            (f for f in files if f.path.rsplit("/", 1)[-1] == "package.json"),
            None,
        )
        configs = [
            f for f in files if f.path.rsplit("/", 1)[-1] in _CONFIG_NAMES
        ]
        cypress_files = [f for f in files if f.path.startswith("cypress/")]

        if package is not None:
            try:
                data = json.loads(package.content)
            except json.JSONDecodeError:
                emissions.append(
                    DetectorEmission(
                        diagnostic=(
                            f"malformed package.json could not be parsed: {package.path}"
                        )
                    )
                )
                data = None
            if isinstance(data, dict):
                deps = _deps(data)
                if "cypress" in deps:
                    emissions.append(_cypress_fact(component_label, package))
                    version = _exact_dep_version(data, "cypress")
                    if version:
                        emissions.append(
                            DetectorEmission(
                                convention=Convention(
                                    name="framework_version",
                                    value=f"cypress=={version}",
                                    evidence_refs=(ref_for(component_label, package),),
                                )
                            )
                        )

        if configs and not any(
            e.fact and e.fact.framework_id == "cypress" for e in emissions
        ):
            emissions.append(_cypress_fact(component_label, configs[0]))

        if configs or cypress_files:
            root_file = configs[0] if configs else cypress_files[0]
            emissions.append(
                DetectorEmission(
                    convention=Convention(
                        name="test_root",
                        value="cypress/",
                        evidence_refs=(ref_for(component_label, root_file),),
                    )
                )
            )
        return emissions


def _cypress_fact(component: str, file: EvidenceFile) -> DetectorEmission:
    return DetectorEmission(
        fact=ProfileFact(
            facet="test_frameworks",
            value="cypress",
            framework_id="cypress",
            confidence="high",
            evidence_refs=(ref_for(component, file),),
        ),
        role="framework",
    )


def _deps(data: dict) -> dict[str, str]:
    merged: dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        block = data.get(key)
        if isinstance(block, dict):
            for name, version in block.items():
                merged[str(name)] = str(version)
    return merged


def _exact_dep_version(data: dict, name: str) -> str | None:
    deps = _deps(data)
    raw = deps.get(name)
    if raw is None:
        return None
    cleaned = raw.lstrip("v=")
    if _EXACT_VERSION.match(cleaned) and not any(
        marker in raw for marker in ("^", "~", ">", "<", "*", "x", "X")
    ):
        return cleaned
    return None
