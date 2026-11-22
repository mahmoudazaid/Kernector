"""Registry of framework generators keyed by framework id (#368)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from packs.software_delivery.test_design.framework_contracts import (
    FrameworkArtifactResult,
    FrameworkSelection,
)
from packs.software_delivery.test_design.models import GeneratedTestCase, TestCoverageDraft


class FrameworkGenerator(Protocol):
    """Render framework-specific tests from confirmed draft cases."""

    framework_id: str

    def generate(
        self,
        draft: TestCoverageDraft,
        selection: FrameworkSelection,
        cases: Sequence[GeneratedTestCase],
    ) -> FrameworkArtifactResult: ...


class FrameworkGeneratorRegistry:
    """Lookup generators by framework id; unknown ids are unsupported."""

    def __init__(self, generators: Sequence[FrameworkGenerator] = ()) -> None:
        self._by_id = {generator.framework_id: generator for generator in generators}

    def get(self, framework_id: str) -> FrameworkGenerator | None:
        return self._by_id.get(framework_id)

    def framework_ids(self) -> frozenset[str]:
        return frozenset(self._by_id)


def default_framework_generator_registry() -> FrameworkGeneratorRegistry:
    from packs.software_delivery.test_design.generators.robot import (
        RobotFrameworkGenerator,
    )

    return FrameworkGeneratorRegistry((RobotFrameworkGenerator(),))
