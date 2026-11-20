"""Technology detectors for project profiling (#387 / #429)."""

from __future__ import annotations

from packs.software_delivery.project_profile.detectors.appium import AppiumDetector
from packs.software_delivery.project_profile.detectors.cucumber import CucumberDetector
from packs.software_delivery.project_profile.detectors.cypress import CypressDetector
from packs.software_delivery.project_profile.detectors.delivery import DeliveryDetector
from packs.software_delivery.project_profile.detectors.junit import JUnitDetector
from packs.software_delivery.project_profile.detectors.node_package import (
    NodePackageDetector,
)
from packs.software_delivery.project_profile.detectors.playwright import (
    PlaywrightDetector,
)
from packs.software_delivery.project_profile.detectors.pytest_framework import (
    PytestFrameworkDetector,
)
from packs.software_delivery.project_profile.detectors.python_manifest import (
    PythonManifestDetector,
)
from packs.software_delivery.project_profile.detectors.robot_framework import (
    RobotFrameworkDetector,
)
from packs.software_delivery.project_profile.detectors.selenium import SeleniumDetector
from packs.software_delivery.project_profile.detectors.specification import (
    SpecificationSyntaxDetector,
)
from packs.software_delivery.project_profile.detectors.testng import TestNGDetector
from packs.software_delivery.project_profile.registry import TechnologyDetectorRegistry


def default_detector_registry() -> TechnologyDetectorRegistry:
    """Return the pack-provided detector set."""
    return TechnologyDetectorRegistry(
        (
            PythonManifestDetector(),
            NodePackageDetector(),
            PlaywrightDetector(),
            PytestFrameworkDetector(),
            CypressDetector(),
            SeleniumDetector(),
            JUnitDetector(),
            TestNGDetector(),
            AppiumDetector(),
            CucumberDetector(),
            RobotFrameworkDetector(),
            DeliveryDetector(),
            SpecificationSyntaxDetector(),
        )
    )
