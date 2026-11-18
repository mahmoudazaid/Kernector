"""Node/TypeScript and frontend framework detection from package.json."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import ClassVar

from packs.software_delivery.project_profile.detectors._refs import ref_for
from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import ProfileFact
from packs.software_delivery.project_profile.registry import DetectorEmission


class NodePackageDetector:
    detector_id = "node_package"
    version = "1"
    facets = frozenset(
        {
            "languages",
            "application_frameworks",
            "test_frameworks",
            "build_and_dependencies",
            "reusable_components",
        }
    )
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]] = {

        "languages": ("package.json", "tsconfig.json"),
        "application_frameworks": ("package.json",),
        "build_and_dependencies": ("package.json", "package-lock.json", "pnpm-lock.yaml"),
        "test_frameworks": (
            "package.json",
            "**/*.spec.ts",
            "**/*.spec.js",
            "**/*.test.ts",
            "**/*.test.js",
            "e2e/**/*.ts",
            "e2e/**/*.js",
        ),
        "reusable_components": (
            "components/**/*.tsx",
            "components/**/*.ts",
            "components/**/*.jsx",
            "components/**/*.js",
            "app/**/page.tsx",
            "app/**/page.ts",
            "app/**/page.jsx",
            "app/**/page.js",
            "lib/api/**/*.ts",
            "lib/api/**/*.tsx",
            "lib/api/**/*.js",
            "lib/api/**/*.jsx",
            "e2e/**/*.ts",
            "e2e/**/*.js",
            "**/*.spec.ts",
            "**/*.spec.js",
            "**/*.test.ts",
            "**/*.test.js",
        ),
    }

    def detect(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        for file in files:
            if file.path.rsplit("/", 1)[-1] != "package.json":
                continue
            try:
                data = json.loads(file.content)
            except json.JSONDecodeError:
                emissions.append(
                    DetectorEmission(
                        diagnostic=f"malformed package.json could not be parsed: {file.path}"
                    )
                )
                continue
            if not isinstance(data, dict):
                continue
            deps = _deps(data)
            ref = ref_for(component_label, file)
            if "typescript" in deps:
                emissions.append(
                    DetectorEmission(
                        fact=ProfileFact(
                            facet="languages",
                            value="TypeScript",
                            language="TypeScript",
                            confidence="high",
                            evidence_refs=(ref,),
                        )
                    )
                )
            for framework_id, dep_name in (
                ("next", "next"),
                ("react", "react"),
            ):
                if dep_name in deps:
                    emissions.append(
                        DetectorEmission(
                            fact=ProfileFact(
                                facet="application_frameworks",
                                value=framework_id,
                                framework_id=framework_id,
                                confidence="high",
                                evidence_refs=(ref,),
                            )
                        )
                    )
            if "@playwright/test" in deps or "playwright" in deps:
                emissions.append(
                    DetectorEmission(
                        fact=ProfileFact(
                            facet="test_frameworks",
                            value="playwright",
                            framework_id="playwright",
                            confidence="high",
                            evidence_refs=(ref,),
                        )
                    )
                )
            if deps:
                emissions.append(
                    DetectorEmission(
                        fact=ProfileFact(
                            facet="build_and_dependencies",
                            value="npm_package",
                            confidence="high",
                            evidence_refs=(ref,),
                        )
                    )
                )
        return emissions


def _deps(data: dict) -> set[str]:
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        block = data.get(key)
        if isinstance(block, dict):
            names.update(str(name) for name in block)
    return names
