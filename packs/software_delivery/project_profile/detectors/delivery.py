"""CI and container delivery detection with conservative stdlib parsing."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import ClassVar

from packs.software_delivery.project_profile.detectors._refs import ref_for
from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import (
    ProfileConfidence,
    ProfileFact,
)
from packs.software_delivery.project_profile.registry import DetectorEmission

_COMPOSE_BASENAMES = frozenset(
    {
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    }
)


class DeliveryDetector:
    detector_id = "delivery"
    version = "1"
    facets = frozenset({"delivery"})
    # Plugin-owned hints: paths this detector understands (CI + containers).
    evidence_recommendations: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "delivery": (
            ".github/workflows/*.yml",
            ".github/workflows/*.yaml",
            ".gitlab-ci.yml",
            "Jenkinsfile",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        ),
    }

    def detect(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> list[DetectorEmission]:
        emissions: list[DetectorEmission] = []
        env_names: set[str] = set()
        for file in files:
            path = file.path
            basename = path.rsplit("/", 1)[-1]
            if basename == "Dockerfile" or path.endswith("/Dockerfile"):
                emissions.append(
                    _fact(component_label, file, "docker", "high")
                )
                env_names.update(_dockerfile_env_names(file.content))
            if basename in _COMPOSE_BASENAMES:
                emissions.append(
                    _fact(component_label, file, "docker_compose", "high")
                )
            if basename == ".gitlab-ci.yml" or path.endswith("/.gitlab-ci.yml"):
                emissions.append(
                    _fact(component_label, file, "gitlab_ci", "high")
                )
            if basename == "Jenkinsfile" or path.endswith("/Jenkinsfile"):
                emissions.append(
                    _fact(component_label, file, "jenkins", "high")
                )
            if "/.github/workflows/" in f"/{path}" or path.startswith(
                ".github/workflows/"
            ):
                if path.endswith((".yml", ".yaml")):
                    jobs = _workflow_job_names(file.content)
                    emissions.append(
                        _fact(component_label, file, "github_actions", "high")
                    )
                    if jobs:
                        emissions.append(
                            _fact(
                                component_label,
                                file,
                                f"github_actions_jobs:{','.join(jobs)}",
                                "medium",
                            )
                        )
                    env_names.update(_workflow_env_names(file.content))
        if env_names:
            emissions.append(
                DetectorEmission(
                    diagnostic=(
                        "delivery env names: "
                        + ", ".join(sorted(env_names))
                    )
                )
            )
        return emissions


def _fact(
    component_label: str,
    file: EvidenceFile,
    value: str,
    confidence: ProfileConfidence,
) -> DetectorEmission:
    return DetectorEmission(
        fact=ProfileFact(
            facet="delivery",
            value=value,
            confidence=confidence,
            evidence_refs=(ref_for(component_label, file),),
        )
    )


def _workflow_job_names(content: str) -> list[str]:
    """Extract job ids under a top-level ``jobs:`` block without a YAML library."""
    lines = content.splitlines()
    in_jobs = False
    jobs: list[str] = []
    for line in lines:
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
            continue
        if in_jobs:
            if line and not line.startswith(" ") and not line.startswith("\t"):
                break
            match = re.match(r"^ {2}([A-Za-z0-9_-]+):\s*$", line)
            if match:
                jobs.append(match.group(1))
    return jobs


def _workflow_env_names(content: str) -> set[str]:
    names: set[str] = set()
    for match in re.finditer(
        r"([A-Z][A-Z0-9_]*)\s*:\s*\$\{\{\s*secrets\.", content
    ):
        names.add(match.group(1))
    return names


def _dockerfile_env_names(content: str) -> set[str]:
    names: set[str] = set()
    for line in content.splitlines():
        match = re.match(r"^ENV\s+([A-Z][A-Z0-9_]*)=", line.strip())
        if match:
            names.add(match.group(1))
    return names
