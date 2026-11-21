"""Playwright depth detection from config and layout evidence (#429)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import ClassVar

from packs.software_delivery.project_profile.detectors._refs import ref_for
from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import Convention, ProfileFact
from packs.software_delivery.project_profile.registry import DetectorEmission

_CONFIG_NAMES = frozenset(
    {
        "playwright.config.ts",
        "playwright.config.js",
        "playwright.config.mjs",
        "playwright.config.cjs",
    }
)
_TEST_DIR_RE = re.compile(
    r"""testDir\s*:\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)


class PlaywrightDetector:
    detector_id = "playwright"
    version = "1"
    facets = frozenset({"test_frameworks", "conventions"})
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "test_frameworks": (
            "playwright.config.ts",
            "playwright.config.js",
            "package.json",
            "**/*.spec.ts",
            "e2e/**/*.ts",
        ),
        "conventions": ("playwright.config.ts", "playwright.config.js", "tests/", "e2e/"),
    }

    def detect(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        config_files = [
            file
            for file in files
            if file.path.rsplit("/", 1)[-1] in _CONFIG_NAMES
        ]
        if not config_files:
            return emissions

        config = config_files[0]
        emissions.append(
            DetectorEmission(
                fact=ProfileFact(
                    facet="test_frameworks",
                    value="playwright",
                    framework_id="playwright",
                    confidence="high",
                    evidence_refs=(ref_for(component_label, config),),
                ),
                role="framework",
            )
        )
        match = _TEST_DIR_RE.search(config.content)
        if match:
            test_dir = match.group(1).rstrip("/") + "/"
            emissions.append(
                DetectorEmission(
                    convention=Convention(
                        name="test_root",
                        value=test_dir,
                        evidence_refs=(ref_for(component_label, config),),
                    )
                )
            )
        else:
            for file in files:
                if file.path.startswith("e2e/") or file.path.startswith("tests/"):
                    root = "e2e/" if file.path.startswith("e2e/") else "tests/"
                    emissions.append(
                        DetectorEmission(
                            convention=Convention(
                                name="test_root",
                                value=root,
                                evidence_refs=(ref_for(component_label, file),),
                            )
                        )
                    )
                    break
        return emissions
