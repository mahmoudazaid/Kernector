"""Composition adapter: Test Design MCP workflow over the existing facade (#338)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace

from application.errors import (
    GitHubNotConnectedError,
    GitHubReauthorizationRequiredError,
    InsufficientEvidenceError,
)
from composition.test_design import (
    CreateTestDesignDraftRequest,
    GenerateTestDesignCasesRequest,
    PatchTestDesignDraftRequest,
    SourceLocatorView,
    TestCoverageDraftView,
    TestDesignFacade,
)
from composition.test_design_errors import (
    TestDesignEvidenceChangedError,
    TestDesignNotFoundError,
    TestDesignUnavailableError,
    TestDesignValidationError,
    TestDesignVersionConflictError,
)
from domain.errors import (
    ToolArgumentValidationError,
    ToolEvidenceChangedError,
    ToolInsufficientEvidenceError,
    ToolSourceNotConnectedError,
    ToolTargetNotFoundError,
    ToolUnavailableError,
    ToolVersionConflictError,
)
from infrastructure.config import Settings
from packs.software_delivery.test_design.models import TestCaseType

_ERROR_MAP: tuple[tuple[type[BaseException], type[Exception]], ...] = (
    (TestDesignNotFoundError, ToolTargetNotFoundError),
    (TestDesignVersionConflictError, ToolVersionConflictError),
    (TestDesignEvidenceChangedError, ToolEvidenceChangedError),
    (GitHubNotConnectedError, ToolSourceNotConnectedError),
    (GitHubReauthorizationRequiredError, ToolSourceNotConnectedError),
    (InsufficientEvidenceError, ToolInsufficientEvidenceError),
    (TestDesignUnavailableError, ToolUnavailableError),
    (TestDesignValidationError, ToolArgumentValidationError),
)


@contextmanager
def _translated_errors() -> Iterator[None]:
    try:
        yield
    except Exception as error:
        for source, target in _ERROR_MAP:
            if isinstance(error, source):
                raise target(target.__doc__ or target.__name__) from error
        raise


def _new_conversation_id() -> str:
    return f"mcp-{uuid.uuid4()}"


class McpTestDesignWorkflow:
    """Implements the pack ``TestDesignWorkflow`` port with existing facade calls."""

    def __init__(
        self,
        facade: TestDesignFacade,
        *,
        conversation_id_factory: Callable[[], str] = _new_conversation_id,
    ) -> None:
        self._facade = facade
        self._conversation_id_factory = conversation_id_factory

    def start(
        self, *, issue_locator: str, conversation_id: str | None
    ) -> TestCoverageDraftView:
        with _translated_errors():
            return self._facade.create_draft(
                CreateTestDesignDraftRequest(
                    conversation_id=conversation_id or self._conversation_id_factory(),
                    source_locator=SourceLocatorView(
                        provider="github", locator=issue_locator
                    ),
                )
            )

    def get(self, *, draft_id: str) -> TestCoverageDraftView:
        with _translated_errors():
            return self._facade.get_draft(draft_id)

    def confirm_selection(
        self,
        *,
        draft_id: str,
        expected_version: int,
        candidate_ids: tuple[str, ...],
    ) -> TestCoverageDraftView:
        """Select *candidate_ids* via ``patch_draft``, then ``confirm_draft``.

        Both calls keep their existing CAS semantics. When confirm fails after
        the patch is saved, the new selection stays at the patched version.
        """
        wanted = frozenset(candidate_ids)
        with _translated_errors():
            current = self._facade.get_draft(draft_id)
            if not wanted <= {item.candidate_id for item in current.candidates}:
                raise TestDesignValidationError(
                    "candidate_ids must reference draft candidates"
                )
            patched = self._facade.patch_draft(
                draft_id,
                PatchTestDesignDraftRequest(
                    expected_version=expected_version,
                    candidates=tuple(
                        replace(item, selected=item.candidate_id in wanted)
                        for item in current.candidates
                    ),
                ),
            )
            return self._facade.confirm_draft(
                draft_id, expected_version=patched.version
            )

    def generate(
        self,
        *,
        draft_id: str,
        expected_version: int,
        candidate_ids: tuple[str, ...] | None,
        type_overrides: tuple[tuple[str, TestCaseType], ...],
        overwrite_edited: bool,
    ) -> TestCoverageDraftView:
        with _translated_errors():
            return self._facade.generate_cases(
                draft_id,
                GenerateTestDesignCasesRequest(
                    expected_version=expected_version,
                    candidate_ids=candidate_ids,
                    type_overrides=type_overrides,
                    overwrite_edited=overwrite_edited,
                ),
            )


def build_mcp_test_design_workflow_factory(
    settings: Settings,
    *,
    facade_factory: Callable[[], TestDesignFacade] | None = None,
) -> Callable[[], McpTestDesignWorkflow]:
    """Return a per-invocation workflow factory bound to the server workspace."""

    def _facade() -> TestDesignFacade:
        if facade_factory is not None:
            return facade_factory()
        from composition.container import build_test_design_facade

        return build_test_design_facade(settings)

    return lambda: McpTestDesignWorkflow(_facade())
