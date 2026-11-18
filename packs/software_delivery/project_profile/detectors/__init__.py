"""MVP technology detectors for project profiling (#387)."""

from __future__ import annotations

from packs.software_delivery.project_profile.detectors.delivery import DeliveryDetector
from packs.software_delivery.project_profile.detectors.node_package import (
    NodePackageDetector,
)
from packs.software_delivery.project_profile.detectors.python_manifest import (
    PythonManifestDetector,
)
from packs.software_delivery.project_profile.detectors.robot_framework import (
    RobotFrameworkDetector,
)
from packs.software_delivery.project_profile.detectors.specification import (
    SpecificationSyntaxDetector,
)
from packs.software_delivery.project_profile.registry import TechnologyDetectorRegistry


def default_detector_registry() -> TechnologyDetectorRegistry:
    """Return the pack-provided MVP detector set."""
    return TechnologyDetectorRegistry(
        (
            PythonManifestDetector(),
            NodePackageDetector(),
            RobotFrameworkDetector(),
            DeliveryDetector(),
            SpecificationSyntaxDetector(),
        )
    )
