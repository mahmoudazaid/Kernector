"""Generate framework-specific tests from a confirmed draft selection (#368)."""

from __future__ import annotations

from dataclasses import dataclass

from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.framework_contracts import FrameworkArtifactResult
from packs.software_delivery.test_design.generators.registry import (
    FrameworkGeneratorRegistry,
    default_framework_generator_registry,
)
from packs.software_delivery.test_design.models import TestCoverageDraft
from packs.software_delivery.test_design.repository import TestCoverageDraftRepository


@dataclass(frozen=True, slots=True)
class GenerateFrameworkTestsRequest:
    draft_id: str
    expected_version: int


class GenerateFrameworkTests:
    """Produce framework artifacts from the draft's confirmed selection."""

    def __init__(
        self,
        *,
        repository: TestCoverageDraftRepository,
        registry: FrameworkGeneratorRegistry | None = None,
    ) -> None:
        self._repository = repository
        self._registry = registry or default_framework_generator_registry()

    def execute(
        self, request: GenerateFrameworkTestsRequest
    ) -> FrameworkArtifactResult:
        if not isinstance(request.expected_version, int) or isinstance(
            request.expected_version, bool
        ):
            raise TestDesignValidationError(
                "expected_version must be a positive integer"
            )
        if request.expected_version <= 0:
            raise TestDesignValidationError(
                "expected_version must be a positive integer"
            )

        draft = self._repository.get(request.draft_id)
        if draft is None:
            raise TestDesignValidationError("draft not found")
        if draft.version != request.expected_version:
            raise TestDesignValidationError("version conflict")
        if draft.status not in {"ready", "case_editing"}:
            raise TestDesignValidationError(
                "generate framework tests requires a confirmed coverage draft"
            )

        selection = draft.framework_selection
        if selection is None:
            return FrameworkArtifactResult(
                status="profile_required",
                framework_id="unknown",
                files=(),
                tests=(),
                implementation_required=(),
                skipped=(),
                untrusted_model_output=False,
                evidence_origin="client_supplied",
            )

        generator = self._registry.get(selection.framework_id)
        if generator is None:
            return FrameworkArtifactResult(
                status="unsupported_framework",
                framework_id=selection.framework_id,
                files=(),
                tests=(),
                implementation_required=(),
                skipped=(),
                untrusted_model_output=False,
                evidence_origin=selection.evidence_origin,
            )

        return generator.generate(draft, selection, draft.generated_cases)


def require_draft_with_selection(draft: TestCoverageDraft) -> None:
    """Helper for callers that need a confirmed selection present."""
    if draft.framework_selection is None:
        raise TestDesignValidationError("framework selection is required")
