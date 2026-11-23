"""Framework generator plugins for Test Design (#368)."""

from packs.software_delivery.test_design.generators.registry import (
    FrameworkGeneratorRegistry,
    default_framework_generator_registry,
)
from packs.software_delivery.test_design.generators.robot import RobotFrameworkGenerator

__all__ = [
    "FrameworkGeneratorRegistry",
    "RobotFrameworkGenerator",
    "default_framework_generator_registry",
]
