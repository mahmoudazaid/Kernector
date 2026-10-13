"""Tool adapter for ``software_delivery.update_xray_tests_from_files`` (#398).

Plan phase: parse the caller's files, read every Jira issue and test the
matcher needs, match each scenario to the existing test it updates and diff it
into a sparse patch. ``dry_run`` returns this plan. Write phase: apply the
planned patches one at a time, in file and line order. Tests are never created.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from domain.errors import ConnectorAuthError
from domain.ports import XrayIssueLookup, XrayTestUpdater
from domain.test_management.xray import (
    JIRA_PATCH_FIELDS,
    JiraIssueSummary,
    XrayTestDetails,
    XrayTestDetailsResult,
    XrayTestPatch,
    XrayUpdateCapabilities,
    XrayUpdateNotConfirmedError,
    XrayUpdateRejectedError,
    XrayUpdateUncertainError,
)
from domain.tool_approval import ApprovalHints
from packs.software_delivery.errors import XrayExportValidationError
from packs.software_delivery.test_files.approval import scenario_titles
from packs.software_delivery.test_files.matching import (
    UpdateMatch,
    lookup_keys,
    match_for_update,
    reject_duplicate_identities,
)
from packs.software_delivery.test_files.models import ParsedTestFile, TestFileTagConfig
from packs.software_delivery.test_files.request import (
    parse_files,
    read_files,
    reject_duplicate_paths,
)
from packs.software_delivery.test_files.xray_diff import DiffProblem, diff_test
from packs.software_delivery.test_files.xray_specs import SpecProblem, build_spec
from packs.software_delivery.tools.xray_calls import call_xray

TOOL_NAME = "software_delivery.update_xray_tests_from_files"
TOOL_DESCRIPTION = (
    "Update existing Xray tests in Jira so they match the scenarios of Cucumber/Gherkin "
    "(.feature) and Robot Framework (.robot) files. Each scenario is matched by its Xray "
    "key tag, then a bare Test issue key, then a test linked to its parent story with the "
    "same summary. Only changed fields are sent; tests are never created or deleted. "
    "Read each file from the workspace yourself and pass its workspace-relative path and "
    "exact full text, unchanged. Set dry_run to true to see the planned updates without "
    "changing Jira. Call the xray_target tool first to confirm the Jira project."
)

_ALLOWED_KEYS = frozenset({"files", "dry_run"})
_STATUSES = ("UPDATED", "WOULD_UPDATE", "SKIPPED", "ERROR")
_APPROVAL_TITLE = "Update Xray tests from files"
_APPROVAL_SUMMARY = (
    "Update existing Jira Test issues in Xray so they match the file scenarios. "
    "Only changed fields are sent; no test is created or deleted. A test switched "
    "between Manual and Cucumber loses its previous steps or Gherkin. When steps "
    "change, a step whose action or expected result changed loses its Xray Data. "
    "Tests outside the configured project are never changed."
)
_DRY_RUN_TITLE = "Dry run: plan Xray test updates from files"
_DRY_RUN_SUMMARY = (
    "Nothing is changed in Jira. Kernector reads Jira to report which tests would be "
    "updated, which are unchanged and which need attention."
)


class XrayFileUpdateBinding(Protocol):
    """Xray clients and configuration the update tool needs from composition."""

    @property
    def lookup(self) -> XrayIssueLookup: ...

    @property
    def updater(self) -> XrayTestUpdater: ...

    @property
    def tags(self) -> TestFileTagConfig: ...

    @property
    def project_key(self) -> str: ...

    @property
    def destination_label(self) -> str: ...

    @property
    def story_issue_types(self) -> frozenset[str]: ...

    @property
    def link_type(self) -> str: ...

    @property
    def default_component(self) -> str | None: ...

    @property
    def update_args_schema(self) -> type | None: ...

    @property
    def update_output_schema(self) -> type | None: ...


def build_update_from_binding(binding: XrayFileUpdateBinding) -> UpdateXrayTestsFromFilesTool:
    """Build the tool from a composition binding (chat and MCP share one shape)."""
    return UpdateXrayTestsFromFilesTool(
        lookup=binding.lookup,
        updater=binding.updater,
        tags=binding.tags,
        project_key=binding.project_key,
        story_issue_types=binding.story_issue_types,
        link_type=binding.link_type,
        default_component=binding.default_component,
        destination_label=binding.destination_label,
        args_schema=binding.update_args_schema,
        output_schema=binding.update_output_schema,
    )


@dataclass(slots=True)
class _Entry:
    match: UpdateMatch
    status: str
    reason: str | None = None
    patch: XrayTestPatch | None = None

    @property
    def changes(self) -> list[str]:
        return list(self.patch.changed) if self.patch is not None else []


class UpdateXrayTestsFromFilesTool:
    """Implements ``domain.ports.Tool``; every call is gated by human approval."""

    def __init__(
        self,
        *,
        lookup: XrayIssueLookup,
        updater: XrayTestUpdater,
        tags: TestFileTagConfig,
        project_key: str,
        story_issue_types: frozenset[str],
        link_type: str,
        default_component: str | None = None,
        destination_label: str | None = None,
        args_schema: type | None = None,
        output_schema: type | None = None,
    ) -> None:
        self._lookup = lookup
        self._updater = updater
        self._tags = tags
        self._project_key = project_key
        self._story_issue_types = story_issue_types
        self._link_type = link_type.strip()
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
        """Safe approval prompt: destination and scenario names, never steps or Jira reads."""
        parsed, dry_run = self._parse(arguments)
        scenarios = [(item, scenario) for item in parsed for scenario in item.scenarios]
        return ApprovalHints(
            title=_DRY_RUN_TITLE if dry_run else _APPROVAL_TITLE,
            summary=_DRY_RUN_SUMMARY if dry_run else _APPROVAL_SUMMARY,
            destination_label=self._destination_label,
            selected_title_count=len(scenarios),
            item_titles=scenario_titles(scenarios),
        )

    def run(self, arguments: Mapping[str, object]) -> str:
        parsed, dry_run = self._parse(arguments)
        entries = self._plan(parsed)
        stop_reason = None if dry_run else self._write(entries)
        return _payload(
            entries,
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
        reject_duplicate_identities(parsed, include_tagged=True)
        return parsed, dry_run

    def _plan(self, parsed: list[ParsedTestFile]) -> list[_Entry]:
        if not any(item.scenarios for item in parsed):
            return []
        issues = call_xray(
            lambda: self._lookup.find_issues(lookup_keys(parsed, include_tagged=True))
        )
        cache: dict[str, tuple[JiraIssueSummary, ...]] = {}

        def linked(story_key: str) -> tuple[JiraIssueSummary, ...]:
            if story_key not in cache:
                cache[story_key] = call_xray(lambda: tuple(self._lookup.linked_tests(story_key)))
            return cache[story_key]

        matches = match_for_update(
            parsed, issues, linked_tests=linked, story_issue_types=self._story_issue_types
        )
        keys = tuple(dict.fromkeys(m.key for m in matches if m.reason is None and m.key))
        details = XrayTestDetailsResult()
        capabilities = XrayUpdateCapabilities(jira_fields=False, story_link_type=False)
        if keys:
            details = call_xray(lambda: self._updater.test_details(keys))
            capabilities = call_xray(self._updater.capabilities)
        by_path = {item.path: item for item in parsed}
        entries: list[_Entry] = []
        for match in matches:
            if match.reason is not None or match.key is None:
                entries.append(_Entry(match, "ERROR", match.reason))
                continue
            current = details.found.get(match.key)
            if current is None or match.key in details.unreadable:
                reason = "details_unreadable" if match.key in details.unreadable else (
                    "details_missing"
                )
                entries.append(_Entry(match, "ERROR", reason))
                continue
            if current.project_key != self._project_key:
                entries.append(_Entry(match, "ERROR", "other_project"))
                continue
            spec = build_spec(
                by_path[match.path],
                match.scenario,
                story_key=match.story_key,
                component=self._default_component,
            )
            if isinstance(spec, SpecProblem):
                entries.append(_Entry(match, "ERROR", spec.reason))
                continue
            story = match.story_key if match.story_problem is None else None
            patch = diff_test(
                spec,
                current,
                component=self._default_component,
                story_key=story,
                link_type=self._link_type,
            )
            if patch is None:
                entries.append(_Entry(match, "SKIPPED"))
            elif isinstance(patch, DiffProblem):
                entries.append(_Entry(match, "ERROR", patch.reason))
            else:
                blocked = _blocked(patch, current, capabilities)
                status = "WOULD_UPDATE" if blocked is None else "ERROR"
                entries.append(_Entry(match, status, blocked, patch=patch))
        return entries

    def _write(self, entries: Sequence[_Entry]) -> str | None:
        """Apply planned patches in order; return the stop reason, if the run stopped.

        Only a definite rejection (nothing written) lets the run continue. An
        auth failure before any successful write raises.
        """
        stop_reason: str | None = None
        wrote = False
        for entry in entries:
            if entry.status != "WOULD_UPDATE" or entry.patch is None:
                continue
            if stop_reason is not None:
                entry.status, entry.reason = "ERROR", "not_attempted"
                continue
            stop_reason = self._update(entry, wrote=wrote)
            wrote = wrote or entry.status == "UPDATED"
        return stop_reason

    def _update(self, entry: _Entry, *, wrote: bool) -> str | None:
        assert entry.patch is not None
        try:
            self._updater.update_test(entry.patch)
        except XrayUpdateRejectedError:
            entry.status, entry.reason = "ERROR", "rejected"
            return None
        except ConnectorAuthError:
            if not wrote:
                raise
            entry.status, entry.reason = "ERROR", "auth_failed"
        except XrayUpdateUncertainError as error:
            entry.status = "ERROR"
            entry.reason = "partially_applied" if error.partial else "outcome_unknown"
        except XrayUpdateNotConfirmedError:
            entry.status, entry.reason = "ERROR", "not_confirmed"
        except Exception:  # noqa: BLE001 - the update may have been written
            entry.status, entry.reason = "ERROR", "outcome_unknown"
        else:
            entry.status = "UPDATED"
            return None
        return entry.reason


def _blocked(  # noqa: PLR0911 - one return per capability check
    patch: XrayTestPatch, details: XrayTestDetails, capabilities: XrayUpdateCapabilities
) -> str | None:
    """Why ``patch`` cannot be written to this test, checked before any write."""
    changed = set(patch.changed)
    if changed & JIRA_PATCH_FIELDS and not capabilities.jira_fields:
        return "jira_fields_unsupported"
    if patch.add_story_link is not None and not capabilities.story_link_type:
        return "link_type_unavailable"
    allowed = details.allowed_components
    if patch.add_component is not None and allowed is not None and (
        patch.add_component not in allowed
    ):
        return "component_not_allowed"
    if not changed <= details.editable:
        return "field_not_editable"
    if patch.kind_change is not None and details.preconditions > 0:
        return "type_change_drops_preconditions"
    return None


def _payload(
    entries: Sequence[_Entry],
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
                    "key": entry.match.key,
                    "candidate_keys": list(entry.match.candidate_keys),
                    "story_key": entry.match.story_key,
                    "story_problem": entry.match.story_problem,
                    "changes": entry.changes,
                    "reason": entry.reason,
                }
                for entry in entries
            ],
            "dry_run": dry_run,
            "counts": counts,
            "stopped": stop_reason is not None,
            "stop_reason": stop_reason,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
