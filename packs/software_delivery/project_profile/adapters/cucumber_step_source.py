"""#298 Cucumber step catalogue adapter for project_profile (#429).

Production catalogue population and matching remain owned by #298. This adapter
implements ``ReusableComponentSource`` against an optional catalogue port. When
no catalogue is bound it returns an empty sequence so composition can wire the
seam without treating fake unit tests as production integration.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from packs.software_delivery.project_profile.intake import ProfileEvidence
from packs.software_delivery.project_profile.models import ReusableComponent


class CucumberStepCataloguePort(Protocol):
    """Minimal port expected from a future #298 step catalogue."""

    def list_step_definitions(
        self, evidence: ProfileEvidence
    ) -> Sequence[ReusableComponent]:
        """Return step_definition components with preserved provenance."""
        ...


class CucumberStepReusableSource:
    """ReusableComponentSource adapter over an optional #298 catalogue port."""

    def __init__(
        self, catalogue: CucumberStepCataloguePort | None = None
    ) -> None:
        self._catalogue = catalogue

    def list_components(
        self, evidence: ProfileEvidence
    ) -> Sequence[ReusableComponent]:
        if self._catalogue is None:
            return ()
        return tuple(self._catalogue.list_step_definitions(evidence))
