"""Tool adapter for ``software_delivery.create_xray_tests_from_files`` (#397).

Plan phase: parse the caller's files, read every Jira issue the matcher needs,
match untagged scenarios to existing tests (shared with #398) and build specs.
``dry_run`` returns this plan. Write phase: create the planned tests one spec
at a time, in file and line order.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from domain.errors import ConnectorAuthError
from domain.ports import XrayIssueLookup, XrayTestImporter
from domain.test_management.xray import (
    JiraIssueSummary,
    XrayRequiredFieldsError,
    XrayTestCreateSchema,
    XrayTestSpec,
)
from domain.tool_approval import ApprovalHints
from packs.software_delivery.errors import XrayExportValidationError
from packs.software_delivery.test_files.approval import scenario_titles
from packs.software_delivery.test_files.matching import (
    ScenarioMatch,
    lookup_keys,
    match_scenarios,
    reject_duplicate_identities,
    untagged,
)
from packs.software_delivery.test_files.models import (
    ParsedTestFile,
    TestFileTagConfig,
)
from packs.software_delivery.test_files.request import (
    parse_files,
    read_files,
    reject_duplicate_paths,
)
from packs.software_delivery.test_files.xray_specs import SpecProblem, build_spec
from packs.software_delivery.tools.xray_calls import call_xray

TOOL_NAME = "software_delivery.create_xray_tests_from_files"
TOOL_DESCRIPTION = (
    "Create Xray tests in Jira for the scenarios of Cucumber/Gherkin (.feature) and "
    "Robot Framework (.robot) files that have no Xray test key tag yet, and link each "
    "test to its parent story. Scenarios that already exist in Jira are reported with "
    "their key instead of being created. Read each file from the workspace yourself "
    "and pass its workspace-relative path and exact full text, unchanged. Set "
    "dry_run to true to see the planned actions without changing Jira. Returns the "
    "created keys mapped to path::scenario so the files can be tagged. Call the "
    "xray_target tool first to confirm the Jira project the tests go to. Do not "
    "start a Test Design draft for existing test files."
)

_ALLOWED_KEYS = frozenset({"files", "dry_run"})
_STATUSES = ("CREATED", "WOULD_CREATE", "EXISTS_UNTAGGED", "AMBIGUOUS", "NO_STORY", "ERROR")
_APPROVAL_TITLE = "Create Xray tests from files"
_APPROVAL_SUMMARY = (
    "Create Jira Test issues in Xray for the file scenarios that have no Xray key yet "
    "and link each one to its story. Existing tests are reported, not created."
)
_DRY_RUN_TITLE = "Dry run: plan Xray tests from files"
_DRY_RUN_SUMMARY = (
    "Nothing is created in Jira. Kernector reads Jira to report which file "
    "scenarios would be created, already exist or need attention."
)


class XrayFileCreateBinding(Protocol):
    """Xray client, configuration and MCP schemas supplied by composition."""

    @property
    def importer(self) -> XrayTestImporter: ...

    @property
    def lookup(self) -> XrayIssueLookup: ...

    @property
    def tags(self) -> TestFileTagConfig: ...

    @property
    def project_key(self) -> str: ...

    @property
    def destination_label(self) -> str: ...

    @property
    def story_issue_types(self) -> frozenset[str]: ...

    @property
    def default_component(self) -> str | None: ...

    @property
    def args_schema(self) -> type | None: ...

    @property
    def output_schema(self) -> type | None: ...

    @property
    def target_args_schema(self) -> type | None: ...

    @property
    def target_output_schema(self) -> type | None: ...


def build_from_binding(binding: XrayFileCreateBinding) -> CreateXrayTestsFromFilesTool:
    """Build the tool from a composition binding (chat and MCP share one shape)."""
    return CreateXrayTestsFromFilesTool(
        importer=binding.importer,
        lookup=binding.lookup,
        tags=binding.tags,
        story_issue_types=binding.story_issue_types,
        default_component=binding.default_component,
        destination_label=binding.destination_label,
        args_schema=binding.args_schema,
        output_schema=binding.output_schema,
    )


@dataclass(slots=True)
class _Entry:
    match: ScenarioMatch
    status: str
    key: str | None = None
    candidate_keys: tuple[str, ...] = ()
    reason: str | None = None
    spec: XrayTestSpec | None = None


class CreateXrayTestsFromFilesTool:
    """Implements ``domain.ports.Tool``; every call is gated by human approval."""

    def __init__(
        self,
        *,
        importer: XrayTestImporter,
        lookup: XrayIssueLookup,
        tags: TestFileTagConfig,
        story_issue_types: frozenset[str],
        default_component: str | None = None,
        destination_label: str | None = None,
        args_schema: type | None = None,
        output_schema: type | None = None,
    ) -> None:
        self._importer = importer
        self._lookup = lookup
        self._tags = tags
        self._story_issue_types = story_issue_types
        self._default_component = default_component
        self._destination_label = destination_label
        self.args_schema = args_schema
        self.output_schema = output_schema

    @property
    def name(self) -> str:
        return TOOL_NAME

    @property
    def description(self) -> str:
        return TOOL_DESCRIPTION

    def approval_hints(self, arguments: Mapping[str, object]) -> ApprovalHints:
        """Safe approval prompt: destination and untagged scenario names, never steps."""
        parsed, dry_run = self._parse(arguments)
        pending = untagged(parsed)
        return ApprovalHints(
            title=_DRY_RUN_TITLE if dry_run else _APPROVAL_TITLE,
            summary=_DRY_RUN_SUMMARY if dry_run else _APPROVAL_SUMMARY,
            destination_label=self._destination_label,
            selected_title_count=len(pending),
            item_titles=scenario_titles(pending),
        )

    def run(self, arguments: Mapping[str, object]) -> str:
        parsed, dry_run = self._parse(arguments)
        entries = self._plan(parsed)
        created: dict[str, str] = {}
        stop_reason = None if dry_run else self._write(entries, created)
        for entry in entries:
            repeat_key = created.get(entry.match.repeat_of or "")
            if repeat_key is not None:
                entry.candidate_keys = (*entry.candidate_keys, repeat_key)
        return _payload(
            entries,
            created,
            dry_run=dry_run,
            stop_reason=stop_reason,
            destination=self._destination_label,
        )

    def _parse(self, arguments: Mapping[str, object]) -> tuple[list[ParsedTestFile], bool]:
        if not isinstance(arguments, Mapping):
            raise XrayExportValidationError("arguments must be an object")
        if "files" not in arguments or set(arguments) - _ALLOWED_KEYS:
            raise XrayExportValidationError("arguments must contain files and optional dry_run")
        dry_run = arguments.get("dry_run", False)
        if not isinstance(dry_run, bool):
            raise XrayExportValidationError("dry_run must be a boolean")
        files = read_files(arguments["files"], XrayExportValidationError)
        reject_duplicate_paths(files)
        parsed = parse_files(files, self._tags)
        reject_duplicate_identities(parsed)
        return parsed, dry_run

    def _plan(self, parsed: list[ParsedTestFile]) -> list[_Entry]:
        if not untagged(parsed):
            return []
        schema = call_xray(self._importer.schema)
        issues = call_xray(lambda: self._lookup.find_issues(lookup_keys(parsed)))
        cache: dict[str, tuple[JiraIssueSummary, ...]] = {}

        def linked(story_key: str) -> tuple[JiraIssueSummary, ...]:
            if story_key not in cache:
                cache[story_key] = call_xray(lambda: tuple(self._lookup.linked_tests(story_key)))
            return cache[story_key]

        matches = match_scenarios(
            parsed, issues, linked_tests=linked, story_issue_types=self._story_issue_types
        )
        by_path = {item.path: item for item in parsed}
        entries: list[_Entry] = []
        for match in matches:
            if match.status != "CREATE":
                entries.append(
                    _Entry(match, match.status, match.key, match.candidate_keys, match.reason)
                )
                continue
            assert match.story_key is not None
            spec = build_spec(
                by_path[match.path],
                match.scenario,
                story_key=match.story_key,
                component=self._default_component,
            )
            problem = spec.reason if isinstance(spec, SpecProblem) else _unsupported(schema, spec)
            if problem is not None:
                entries.append(_Entry(match, "ERROR", reason=problem))
                continue
            assert isinstance(spec, XrayTestSpec)
            entries.append(_Entry(match, "WOULD_CREATE", spec=spec))
        return entries

    def _write(self, entries: Sequence[_Entry], created: dict[str, str]) -> str | None:
        """Create planned tests in order; return the stop reason, if the run stopped.

        Each ``import_tests`` call holds one spec, so the importer's batch-local
        stop rule never spans scenarios; stopping lives here. Only a definite
        rejection (nothing written) lets the run continue.
        """
        stop_reason: str | None = None
        for entry in entries:
            if entry.status != "WOULD_CREATE" or entry.spec is None:
                continue
            if stop_reason is not None:
                entry.status, entry.reason = "ERROR", "not_attempted"
                continue
            stop_reason = self._create(entry, created)
        return stop_reason

    def _create(self, entry: _Entry, created: dict[str, str]) -> str | None:
        assert entry.spec is not None
        try:
            result = self._importer.import_tests([entry.spec])
        except XrayRequiredFieldsError:
            entry.status, entry.reason = "ERROR", "required_fields"
            return None
        except ConnectorAuthError:
            if not created:
                raise
            entry.status, entry.reason = "ERROR", "auth_failed"
            return entry.reason
        except Exception:  # noqa: BLE001 - the create may have been written
            entry.status, entry.reason = "ERROR", "outcome_unknown"
            return entry.reason
        if len(result.created_keys) == 1:
            key = result.created_keys[0]
            created[entry.match.identity] = key
            entry.key = key
            warning = next((w for w in result.warnings if w.key == key), None)
            if warning is not None:
                entry.status, entry.reason = "ERROR", warning.reason
                return entry.reason
            entry.status = "CREATED"
            return None
        if not result.created_keys and result.failed_count == 1:
            entry.status, entry.reason = "ERROR", "rejected"
            return None
        entry.status, entry.reason = "ERROR", "outcome_unknown"
        return entry.reason


def _unsupported(schema: XrayTestCreateSchema, spec: XrayTestSpec) -> str | None:
    """Reason the project cannot create ``spec`` exactly as built; never downgrade it."""
    if spec.kind == "manual" and not schema.supports_manual:
        return "manual_unsupported"
    if spec.kind == "cucumber" and not schema.supports_cucumber:
        return "cucumber_unsupported"
    if spec.outline and not schema.supports_cucumber_outline:
        return "outline_unsupported"
    if not schema.supports_issue_link:
        return "link_unsupported"
    return None


def _payload(
    entries: Sequence[_Entry],
    created: Mapping[str, str],
    *,
    dry_run: bool,
    stop_reason: str | None,
    destination: str | None,
) -> str:
    counts = dict.fromkeys(_STATUSES, 0)
    for entry in entries:
        counts[entry.status] += 1
    return json.dumps(
        {
            "destination": destination,
            "results": [
                {
                    "path": entry.match.path,
                    "line": entry.match.scenario.line,
                    "summary": entry.match.scenario.summary,
                    "status": entry.status,
                    "key": entry.key,
                    "candidate_keys": list(entry.candidate_keys),
                    "story_key": entry.match.story_key,
                    "reason": entry.reason,
                }
                for entry in entries
            ],
            "created": dict(created),
            "dry_run": dry_run,
            "counts": counts,
            "stopped": stop_reason is not None,
            "stop_reason": stop_reason,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )

