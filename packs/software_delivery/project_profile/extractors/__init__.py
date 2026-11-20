"""Framework-specific reusable-component extractors (#387 / #429).

Each framework owns its extractor. Register new frameworks here without
changing Robot, frontend, or Playwright modules.
"""

from __future__ import annotations

from packs.software_delivery.project_profile.extractors.cypress_support import (
    CypressSupportExtractor,
)
from packs.software_delivery.project_profile.extractors.frontend_paths import (
    FrontendPathExtractor,
)
from packs.software_delivery.project_profile.extractors.playwright_specs import (
    PlaywrightSpecExtractor,
)
from packs.software_delivery.project_profile.extractors.pytest_fixtures import (
    PytestFixtureExtractor,
)
from packs.software_delivery.project_profile.extractors.robot_keywords import (
    RobotKeywordExtractor,
)
from packs.software_delivery.project_profile.extractors.selenium_pages import (
    SeleniumPageExtractor,
)


def default_extractors() -> tuple:
    """Return the pack extractor set (one plugin per framework family)."""
    return (
        RobotKeywordExtractor(),
        FrontendPathExtractor(),
        PlaywrightSpecExtractor(),
        PytestFixtureExtractor(),
        CypressSupportExtractor(),
        SeleniumPageExtractor(),
    )
