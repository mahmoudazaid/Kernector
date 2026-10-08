"""Tool adapter for ``software_delivery.create_xray_tests`` (#199)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Protocol, TypeVar

from domain.errors import (
    ConnectorAuthError,
    ConnectorUnavailableError,
    ToolFailureError,
)
from domain.ports import XrayTestImporter
from domain.test_management.xray import (
    XrayRequiredFieldsError,
    XrayTestCreateSchema,
    XrayTestSpec,
    XrayTestStep,
)
from domain.tool_approval import ApprovalHints
from packs.software_delivery.errors import XrayExportValidationError
from packs.software_delivery.test_design.models import (
    GeneratedTestCase,
    TestCoverageDraft,
)

TOOL_NAME = "software_delivery.create_xray_tests"
TOOL_DESCRIPTION = (
    "Create Xray tests from the generated cases of a Software Delivery "
    "Test Design draft."
)

_MSG_DRAFT_NOT_FOUND = "Test Design draft not found"
_MSG_NOTHING_TO_CREATE = "The draft has no generated test cases ready to create"
_MSG_UNSUPPORTED = "The Xray project cannot create these tests"
_MSG_NOTHING_CREATED = "Xray did not create any tests"
_MSG_XRAY_UNAVAILABLE = "Xray is temporarily unavailable"
_MSG_XRAY_FAILED = "Creating Xray tests failed"
_MSG_REQUIRED_FIELDS = (
    "The Xray project requires Jira fields Kernector could not fill from the "
    "source issue or allowed values; nothing was created"
)
_MAX_FIELD_NAMES = 10
_ALLOWED_KEYS = frozenset({"draft_id", "link_source_issue"})
_MAX_DRAFT_ID_CHARS = 128

_APPROVAL_TITLE = "Create Xray tests"
_APPROVAL_SUMMARY = (
    "Create new Jira Test issues in Xray from the generated Test Design cases. "
    "Each approval creates new tests."
)

DraftLoader = Callable[[str], TestCoverageDraft | None]
CreatedRecorder = Callable[[str, tuple[str, ...]], None]
"""Receives ``(draft_id, created_keys)`` after a run created at least one test."""
_T = TypeVar("_T")


class XrayMcpBinding(Protocol):
    """Workspace-bound collaborators and MCP schemas supplied by composition."""

    @property
    def importer(self) -> XrayTestImporter: ...

    @property
    def load_draft(self) -> DraftLoader: ...

    @property
    def project_key(self) -> str: ...

    @property
    def on_created(self) -> CreatedRecorder | None: ...

    @property
    def args_schema(self) -> type: ...

    @property
    def output_schema(self) -> type: ...


class CreateXrayTestsTool:
    """Implements ``domain.ports.Tool`` for creating Xray tests from a draft."""

    def __init__(
        self,
        *,
        load_draft: DraftLoader,
        importer: XrayTestImporter,
        destination_label: str | None = None,
        on_created: CreatedRecorder | None = None,
        args_schema: type | None = None,
        output_schema: type | None = None,
    ) -> None:
        self._load_draft = load_draft
        self._importer = importer
        self._destination_label = destination_label
        self._on_created = on_created
        self.args_schema = args_schema
        self.output_schema = output_schema

    @property
    def name(self) -> str:
        return TOOL_NAME

    @property
    def description(self) -> str:
        return TOOL_DESCRIPTION

    def approval_hints(self, arguments: Mapping[str, object]) -> ApprovalHints:
        """Safe approval prompt: destination and test count, never draft content."""
        return ApprovalHints(
            title=_APPROVAL_TITLE,
            summary=_APPROVAL_SUMMARY,
            destination_label=self._destination_label,
            selected_title_count=len(self._specs(arguments)),
        )

    def run(self, arguments: Mapping[str, object]) -> str:
        specs = self._specs(arguments)
        schema = _call_xray(self._importer.schema)
        if not _supported(schema, specs):
            raise ToolFailureError(_MSG_UNSUPPORTED)
        result = _call_xray(lambda: self._importer.import_tests(specs))
        if not result.created_keys:
            raise ToolFailureError(_MSG_NOTHING_CREATED)
        if self._on_created is not None:
            draft_id, _ = _parse_request(arguments)
            self._on_created(draft_id, tuple(result.created_keys))
        return json.dumps(
            {
                "created_keys": list(result.created_keys),
                "created_count": len(result.created_keys),
                "failed_count": result.failed_count,
            },
            separators=(",", ":"),
        )

    def _specs(self, arguments: Mapping[str, object]) -> tuple[XrayTestSpec, ...]:
        draft_id, link_source_issue = _parse_request(arguments)
        draft = self._load_draft(draft_id)
        if draft is None:
            raise XrayExportValidationError(_MSG_DRAFT_NOT_FOUND)
        source_key = jira_issue_key(draft)
        link_key = source_key if link_source_issue else None
        specs = tuple(
            replace(spec, link_issue_key=link_key, source_issue_key=source_key)
            for spec in _specs_from_draft(draft)
        )
        if not specs:
            raise XrayExportValidationError(_MSG_NOTHING_TO_CREATE)
        return specs


_SCENARIO_HEADERS = ("scenario:", "scenario outline:", "scenario template:", "example:")
_BACKGROUND_HEADERS = ("background:",)
_JIRA_ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]*-[1-9][0-9]*$")


def _call_xray(call: Callable[[], _T]) -> _T:
    try:
        return call()
    except ConnectorAuthError:
        raise
    except XrayRequiredFieldsError as exc:
        names = ", ".join(exc.field_names[:_MAX_FIELD_NAMES])
        raise ToolFailureError(f"{_MSG_REQUIRED_FIELDS}: {names}") from exc
    except ConnectorUnavailableError as exc:
        raise ToolFailureError(_MSG_XRAY_UNAVAILABLE) from exc
    except Exception as exc:  # noqa: BLE001 - map connector and unexpected failures
        raise ToolFailureError(_MSG_XRAY_FAILED) from exc


def _parse_request(arguments: Mapping[str, object]) -> tuple[str, bool]:
    if not isinstance(arguments, Mapping):
        raise XrayExportValidationError("arguments must be an object")
    if set(arguments) - _ALLOWED_KEYS:
        raise XrayExportValidationError("arguments contain unsupported keys")
    draft_id = arguments.get("draft_id")
    if not isinstance(draft_id, str) or not draft_id.strip():
        raise XrayExportValidationError("draft_id must be a non-empty string")
    if len(draft_id.strip()) > _MAX_DRAFT_ID_CHARS:
        raise XrayExportValidationError(
            f"draft_id must be at most {_MAX_DRAFT_ID_CHARS} characters"
        )
    link_source_issue = arguments.get("link_source_issue", True)
    if not isinstance(link_source_issue, bool):
        raise XrayExportValidationError("link_source_issue must be a boolean")
    return draft_id.strip(), link_source_issue


def _supported(schema: XrayTestCreateSchema, specs: Sequence[XrayTestSpec]) -> bool:
    kinds = {spec.kind for spec in specs}
    if "manual" in kinds and not schema.supports_manual:
        return False
    if "cucumber" in kinds and not schema.supports_cucumber:
        return False
    linking = any(spec.link_issue_key is not None for spec in specs)
    return schema.supports_issue_link or not linking


def jira_issue_key(draft: TestCoverageDraft) -> str | None:
    """Return the Jira story key the draft's Xray tests link to, if any."""
    key = draft.ticket_identifier.strip()
    if draft.source_provider != "jira" or _JIRA_ISSUE_KEY.fullmatch(key) is None:
        return None
    return key


def _specs_from_draft(draft: TestCoverageDraft) -> tuple[XrayTestSpec, ...]:
    titles = {c.candidate_id: c.title.strip() for c in draft.candidates if c.selected}
    specs: list[XrayTestSpec] = []
    for case in draft.generated_cases:
        title = titles.get(case.candidate_id)
        if title is None or case.availability != "available":
            continue
        if case.test_type == "cucumber":
            specs.append(_cucumber_spec(title, case, draft.cucumber_background))
        else:
            specs.append(_manual_spec(title, case))
    return tuple(specs)


def _cucumber_spec(title: str, case: GeneratedTestCase, background: str) -> XrayTestSpec:
    lines = _step_lines(background, _BACKGROUND_HEADERS)
    lines.extend(_step_lines(case.gherkin, _SCENARIO_HEADERS))
    return XrayTestSpec(title=title, kind="cucumber", gherkin="\n".join(lines))


def _step_lines(text: str, headers: tuple[str, ...]) -> list[str]:
    return [
        line
        for line in (raw.strip() for raw in text.splitlines())
        if line and not line.lower().startswith(headers)
    ]


def _manual_spec(title: str, case: GeneratedTestCase) -> XrayTestSpec:
    actions = [step.strip() for step in case.steps if step.strip()]
    expected = "\n".join(
        line.strip() for line in case.expected_result.splitlines() if line.strip()
    )
    last = len(actions) - 1
    return XrayTestSpec(
        title=title,
        kind="manual",
        preconditions=case.preconditions.strip(),
        steps=tuple(
            XrayTestStep(action=action, expected=expected if index == last else "")
            for index, action in enumerate(actions)
        ),
    )
