"""Framework-specific reusable-component extractors (#387).

Each framework owns its extractor. Register new frameworks here without
changing Robot, frontend, or Playwright modules.
"""

from __future__ import annotations

from packs.software_delivery.project_profile.extractors.frontend_paths import (
    FrontendPathExtractor,
)
from packs.software_delivery.project_profile.extractors.playwright_specs import (
    PlaywrightSpecExtractor,
)
from packs.software_delivery.project_profile.extractors.robot_keywords import (
    RobotKeywordExtractor,
)


def default_extractors() -> tuple[
    RobotKeywordExtractor, FrontendPathExtractor, PlaywrightSpecExtractor
]:
    """Return the MVP extractor set (one plugin per framework family)."""
    return (
        RobotKeywordExtractor(),
        FrontendPathExtractor(),
        PlaywrightSpecExtractor(),
    )
