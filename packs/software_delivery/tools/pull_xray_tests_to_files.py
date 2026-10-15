"""Tool adapter for ``software_delivery.pull_xray_tests_to_files`` (#400).

Reads Jira/Xray and returns Robot / Gherkin file proposals. Never writes Jira
or disk. Every call needs human approval; new-file paths are suggestions the
caller can override via ``new_file_paths`` / ``new_file_name_template``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from domain.ports import XrayIssueLookup, XrayTestUpdater
from domain.test_management.xray import (
    IssueLinkDirection,
    JiraIssueSummary,
    StoryNamingContext,
    XrayTestDetails,
)
from domain.tool_approval import ApprovalHints
from packs.software_delivery.errors import PullXrayValidationError, TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.limits import (
    MAX_PULL_XRAY_RESULT_BYTES,
    MAX_PULL_XRAY_TESTS,
    MAX_TEST_FILE_BYTES,
    MAX_TEST_FILE_PATH_CHARS,
    MAX_TEST_FILE_SCENARIOS,
    MAX_TEST_FILES,
    MAX_TEST_FILES_TOTAL_BYTES,
)
from packs.software_delivery.test_files.approval import (
    MAX_APPROVAL_TITLE_CHARS,
    MAX_APPROVAL_TITLES,
)
from packs.software_delivery.test_files.from_xray import (
    RenderUnsupported,
    ScenarioRender,
    new_file_text,
    render_scenario,
    with_story_tag,
)
from packs.software_delivery.test_files.models import ParsedTestFile, TestFileTagConfig
from packs.software_delivery.test_files.parser import is_supported_test_file, parse_test_file
from packs.software_delivery.test_files.pull_apply import (
    AddEdit,
    BackfillEdit,
    apply_pull_edits,
)
from packs.software_delivery.test_files.pull_parent import (
    inventory_matches,
    known_xray_keys,
    resolve_parent,
    validate_scope_story,
)
from packs.software_delivery.test_files.pull_target import (
    TargetAmbiguous,
    TargetNamingFailed,
    new_path_collides,
    propose_target,
    validate_relative_path,
    validate_template,
)
from packs.software_delivery.test_files.request import reject_duplicate_paths
from packs.software_delivery.tools.xray_calls import call_xray

TOOL_NAME = "software_delivery.pull_xray_tests_to_files"
TOOL_DESCRIPTION = (
    "Pull Xray tests that exist only in Jira into Robot Framework (.robot) or "
    "Cucumber/Gherkin (.feature) scenario proposals. Prefer an existing suite or "
    "feature already tagged with the parent story; only suggest a new file when "
    "none matches. New paths come from XRAY_NEW_FILE_NAME_TEMPLATE (overridable "
    "per call) and can be changed via new_file_paths before approval. Pass local "
    "files as path+content so known XRay keys are skipped. dry_run plans without "
    "file content/diffs. Kernector writes nothing to Jira or disk; every call "
    "needs human approval."
)

_APPROVAL_TITLE = "Pull Xray tests into files"
_DRY_RUN_TITLE = "Preview pull of Xray tests into files"
_APPROVAL_SUMMARY = (
    "Adds or tags scenarios from Jira into existing test files when possible; "
    "new file names are suggestions you can override with new_file_paths."
)
_DRY_RUN_SUMMARY = (
    "Plans which scenarios would be added, tagged, or suggested as new files; "
    "does not return file content."
)

_FORMATS = frozenset({"robot", "feature"})
_ACTIONABLE = frozenset({"ADD", "BACKFILL_TAG", "NEW_FILE"})
_STATUSES = (
    "ADD",
    "WOULD_ADD",
    "BACKFILL_TAG",
    "WOULD_BACKFILL_TAG",
    "NEW_FILE",
    "WOULD_NEW_FILE",
    "SKIP_KNOWN",
    "SKIP_NO_STORY",
    "STORY_UNRESOLVED",
    "STORY_MISSING",
    "STORY_NOT_QUALIFYING",
    "STORY_AMBIGUOUS",
    "STORY_LINK_UNCONFIRMED",
    "UNREADABLE",
    "UNSUPPORTED",
    "KEY_CONFLICT",
    "LOCAL_AMBIGUOUS",
    "REMOTE_AMBIGUOUS",
    "TARGET_AMBIGUOUS",
    "PATH_COLLISION",
    "NAMING_FAILED",
    "LIMIT_EXCEEDED",
)

_PARENT_STATUS = {
    "skip_no_story": "SKIP_NO_STORY",
    "story_unresolved": "STORY_UNRESOLVED",
    "story_missing": "STORY_MISSING",
    "story_not_qualifying": "STORY_NOT_QUALIFYING",
    "story_ambiguous": "STORY_AMBIGUOUS",
    "story_link_unconfirmed": "STORY_LINK_UNCONFIRMED",
}

_FILE_KEYS = frozenset({"path", "content"})


class XrayFilePullBinding(Protocol):
    @property
    def lookup(self) -> XrayIssueLookup: ...

    @property
    def updater(self) -> XrayTestUpdater: ...

    @property
    def tags(self) -> TestFileTagConfig: ...

    @property
    def project_key(self) -> str: ...

    @property
    def story_issue_types(self) -> frozenset[str]: ...

    @property
    def link_type(self) -> str: ...

    @property
    def link_direction(self) -> IssueLinkDirection: ...

    @property
    def default_component(self) -> str | None: ...

    @property
    def new_file_name_template(self) -> str: ...

    @property
    def destination_label(self) -> str: ...

    @property
    def pull_args_schema(self) -> type | None: ...

    @property
    def pull_output_schema(self) -> type | None: ...


def build_pull_from_binding(binding: XrayFilePullBinding) -> PullXrayTestsToFilesTool:
    return PullXrayTestsToFilesTool(
        lookup=binding.lookup,
        updater=binding.updater,
        tags=binding.tags,
        project_key=binding.project_key,
        story_issue_types=binding.story_issue_types,
        link_type=binding.link_type,
        link_direction=binding.link_direction,
        default_component=binding.default_component,
        new_file_name_template=binding.new_file_name_template,
        destination_label=binding.destination_label,
        args_schema=binding.pull_args_schema,
        output_schema=binding.pull_output_schema,
    )


@dataclass(slots=True)
class _Result:
    key: str
    summary: str
    format: str
    status: str
    reason: str | None = None
    story_key: str | None = None
    path: str | None = None
    line: int | None = None
    candidate_keys: tuple[str, ...] = ()
    candidate_identities: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    render: ScenarioRender | None = None
    action: Literal["add", "backfill", "new"] | None = None


@dataclass(slots=True)
class _ParsedArgs:
    story_key: str | None
    project: bool
    component: str | None
    files: list[tuple[str, str]]
    formats: tuple[str, ...]
    dry_run: bool
    template: str
    new_file_paths: dict[str, str]


class PullXrayTestsToFilesTool:
    """Implements ``domain.ports.Tool``; proposals need human approval."""

    def __init__(
        self,
        *,
        lookup: XrayIssueLookup,
        updater: XrayTestUpdater,
        tags: TestFileTagConfig,
        project_key: str,
        story_issue_types: frozenset[str],
        link_type: str,
        link_direction: IssueLinkDirection = "outward",
        default_component: str | None = None,
        new_file_name_template: str = "{epic_summary}__{story_summary}",
        destination_label: str | None = None,
        args_schema: type | None = None,
        output_schema: type | None = None,
    ) -> None:
        self._lookup = lookup
        self._updater = updater
        self._tags = tags
        self._project_key = project_key
        self._story_issue_types = story_issue_types
        self._link_type = link_type
        self._link_direction = link_direction
        self._default_component = default_component
        self._template = new_file_name_template
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
        """Safe approval prompt: destination, inventory, and chosen/suggested paths."""
        parsed = self._parse(arguments)
        titles = _approval_titles(parsed)
        return ApprovalHints(
            title=_DRY_RUN_TITLE if parsed.dry_run else _APPROVAL_TITLE,
            summary=_DRY_RUN_SUMMARY if parsed.dry_run else _APPROVAL_SUMMARY,
            destination_label=self._destination_label,
            selected_title_count=len(titles),
            item_titles=_capped_titles(titles),
        )

    def run(self, arguments: Mapping[str, object]) -> str:
        parsed = self._parse(arguments)
        inventory = self._parse_inventory(parsed.files)
        known = known_xray_keys(inventory)
        remote = self._remote_tests(parsed)
        if len(remote) > MAX_PULL_XRAY_TESTS:
            raise PullXrayValidationError(
                f"too many remote tests ({len(remote)}); limit is {MAX_PULL_XRAY_TESTS}"
            )
        pending_keys = [item.key for item in remote if item.key not in known]
        details = (
            call_xray(lambda: self._updater.test_details(pending_keys))
            if pending_keys
            else None
        )
        results: list[_Result] = []
        proposed_paths: dict[str, str] = {}
        for item in remote:
            for fmt in parsed.formats:
                if item.key in known:
                    results.append(
                        _Result(item.key, item.summary, fmt, "SKIP_KNOWN")
                    )
                    continue
                if details is None or item.key in details.unreadable:
                    results.append(_Result(item.key, item.summary, fmt, "UNREADABLE"))
                    continue
                detail = details.found.get(item.key)
                if detail is None:
                    results.append(_Result(item.key, item.summary, fmt, "UNREADABLE"))
                    continue
                planned = self._plan_one(
                    detail,
                    fmt,
                    inventory,
                    parsed,
                    proposed_paths,
                )
                for result in planned:
                    if result.action == "new" and result.path and result.story_key:
                        proposed_paths.setdefault(result.path, result.story_key)
                results.extend(planned)

        self._mark_remote_ambiguous(results)
        files_out: list[dict[str, object]] = []
        if not parsed.dry_run:
            files_out = self._apply(results, parsed.files, inventory)

        payload = _payload(results, files_out, parsed, self._project_key)
        if len(payload.encode("utf-8")) > MAX_PULL_XRAY_RESULT_BYTES:
            raise TestFileValidationError(None, None, Reason.RESULT_TOO_LARGE)
        return payload

    def _plan_one(
        self,
        detail: XrayTestDetails,
        fmt: str,
        inventory: list[ParsedTestFile],
        parsed: _ParsedArgs,
        proposed_paths: Mapping[str, str],
    ) -> list[_Result]:
        required_story = parsed.story_key
        dry_run = parsed.dry_run
        parent = resolve_parent(
            detail,
            link_type=self._link_type,
            link_direction=self._link_direction,
            story_issue_types=self._story_issue_types,
            find_issues=lambda keys: call_xray(lambda: self._lookup.find_issues(keys)),
            required_story_key=required_story,
        )
        if parent.status != "ok":
            status = _PARENT_STATUS[parent.status]
            return [
                _Result(
                    detail.key,
                    detail.summary,
                    fmt,
                    status,
                    story_key=parent.story_key,
                    candidate_keys=parent.candidate_keys,
                )
            ]
        assert parent.story_key is not None
        story_key = parent.story_key
        rendered = render_scenario(detail, fmt, self._tags)
        warnings = rendered.warnings
        if isinstance(rendered, RenderUnsupported):
            return [
                _Result(
                    detail.key,
                    detail.summary,
                    fmt,
                    "UNSUPPORTED",
                    reason=rendered.reason,
                    story_key=story_key,
                    warnings=warnings,
                )
            ]

        matches = inventory_matches(
            inventory, story_key=story_key, fmt=fmt, summary=detail.summary
        )
        if len(matches) > 1:
            identities = tuple(f"{path}::{detail.summary}" for path, _ in matches)
            return [
                _Result(
                    detail.key,
                    detail.summary,
                    fmt,
                    "LOCAL_AMBIGUOUS",
                    story_key=story_key,
                    candidate_identities=identities,
                    warnings=warnings,
                )
            ]
        if len(matches) == 1:
            path, scenario = matches[0]
            if scenario.xray_key and scenario.xray_key != detail.key:
                return [
                    _Result(
                        detail.key,
                        detail.summary,
                        fmt,
                        "KEY_CONFLICT",
                        reason="different_local_key",
                        story_key=story_key,
                        path=path,
                        line=scenario.line,
                        candidate_keys=(scenario.xray_key,),
                        warnings=warnings,
                    )
                ]
            if scenario.xray_key is None:
                status = "WOULD_BACKFILL_TAG" if dry_run else "BACKFILL_TAG"
                return [
                    _Result(
                        detail.key,
                        detail.summary,
                        fmt,
                        status,
                        story_key=story_key,
                        path=path,
                        line=scenario.line,
                        warnings=warnings,
                        render=rendered,
                        action="backfill",
                    )
                ]
            return [
                _Result(detail.key, detail.summary, fmt, "SKIP_KNOWN", story_key=story_key, path=path)
            ]

        naming = call_xray(lambda: self._lookup.story_naming_context(story_key))
        target = propose_target(
            story_key=story_key,
            fmt=fmt,
            inventory=inventory,
            naming=naming,
            template=parsed.template,
            proposed_paths=proposed_paths,
        )
        if isinstance(target, TargetAmbiguous):
            return [
                _Result(
                    detail.key,
                    detail.summary,
                    fmt,
                    "TARGET_AMBIGUOUS",
                    story_key=story_key,
                    candidate_identities=target.paths,
                    warnings=warnings,
                )
            ]
        if isinstance(target, TargetNamingFailed):
            status = "PATH_COLLISION" if target.reason == "path_collision" else "NAMING_FAILED"
            return [
                _Result(
                    detail.key,
                    detail.summary,
                    fmt,
                    status,
                    reason=target.reason,
                    story_key=story_key,
                    warnings=warnings,
                )
            ]
        if target.kind == "existing":
            status = "WOULD_ADD" if dry_run else "ADD"
            if fmt == "robot" and not _file_level_story(inventory, target.path):
                rendered = with_story_tag(rendered, story_key, self._tags)
            return [
                _Result(
                    detail.key,
                    detail.summary,
                    fmt,
                    status,
                    story_key=story_key,
                    path=target.path,
                    warnings=warnings,
                    render=rendered,
                    action="add",
                )
            ]
        path = target.path
        override = parsed.new_file_paths.get(story_key)
        if override is not None:
            resolved = _resolve_override_path(
                override,
                fmt=fmt,
                story_key=story_key,
                inventory=inventory,
                proposed_paths=proposed_paths,
            )
            if isinstance(resolved, TargetNamingFailed):
                status = (
                    "PATH_COLLISION" if resolved.reason == "path_collision" else "NAMING_FAILED"
                )
                return [
                    _Result(
                        detail.key,
                        detail.summary,
                        fmt,
                        status,
                        reason=resolved.reason,
                        story_key=story_key,
                        warnings=warnings,
                    )
                ]
            path = resolved
        status = "WOULD_NEW_FILE" if dry_run else "NEW_FILE"
        return [
            _Result(
                detail.key,
                detail.summary,
                fmt,
                status,
                story_key=story_key,
                path=path,
                warnings=warnings,
                render=rendered,
                action="new",
            )
        ]

    def _mark_remote_ambiguous(self, results: list[_Result]) -> None:
        groups: dict[tuple[str, str, str], list[_Result]] = {}
        for result in results:
            if result.status not in _ACTIONABLE and not result.status.startswith("WOULD_"):
                continue
            if result.story_key is None:
                continue
            key = (result.story_key, result.format, result.summary)
            groups.setdefault(key, []).append(result)
        for group in groups.values():
            if len(group) < 2:
                continue
            keys = tuple(item.key for item in group)
            for item in group:
                item.status = "REMOTE_AMBIGUOUS"
                item.action = None
                item.render = None
                item.candidate_keys = keys

    def _apply(
        self,
        results: list[_Result],
        files: list[tuple[str, str]],
        inventory: list[ParsedTestFile],
    ) -> list[dict[str, object]]:
        inventory_map = dict(files)
        parsed_by_path = {parsed.path: parsed for parsed in inventory}
        adds: list[AddEdit] = []
        backfills: list[BackfillEdit] = []
        new_by_path: dict[str, list[_Result]] = {}
        for result in results:
            if result.action is None or result.path is None or result.render is None:
                continue
            if result.action == "backfill":
                backfills.append(BackfillEdit(result.path, result.summary, result.key))
            elif result.action == "add":
                adds.append(AddEdit(result.path, result.render))
            else:
                claimed = new_by_path.get(result.path)
                if result.path in inventory_map or (
                    claimed and claimed[0].story_key != result.story_key
                ):
                    result.status = "PATH_COLLISION"
                    result.action = None
                    continue
                new_by_path.setdefault(result.path, []).append(result)

        new_files: dict[str, str] = {}
        naming_cache: dict[str, StoryNamingContext] = {}
        for path, group in new_by_path.items():
            story_key = group[0].story_key
            assert story_key is not None
            if story_key not in naming_cache:
                naming_cache[story_key] = call_xray(
                    lambda key=story_key: self._lookup.story_naming_context(key)
                )
            naming = naming_cache[story_key]
            fmt = group[0].format
            renders = tuple(item.render for item in group if item.render is not None)
            new_files[path] = new_file_text(
                fmt=fmt,
                story_key=story_key,
                story_summary=naming.story_summary,
                scenarios=renders,
                tags=self._tags,
            )

        proposals = apply_pull_edits(
            inventory_map,
            adds=adds,
            backfills=backfills,
            new_files=new_files,
            tags=self._tags,
            parsed_by_path=parsed_by_path,
        )
        return [
            {
                "path": proposal.path,
                "content": proposal.content,
                "diff": proposal.diff,
                "changed": True,
            }
            for proposal in proposals
        ]

    def _remote_tests(self, parsed: _ParsedArgs) -> tuple[JiraIssueSummary, ...]:
        if parsed.story_key is not None:
            failure = validate_scope_story(
                parsed.story_key,
                story_issue_types=self._story_issue_types,
                find_issues=lambda keys: call_xray(lambda: self._lookup.find_issues(keys)),
            )
            if failure is not None:
                raise PullXrayValidationError(failure)
            listed = call_xray(lambda: self._lookup.linked_tests(parsed.story_key or ""))
        else:
            listed = call_xray(
                lambda: self._lookup.list_tests(self._project_key, component=parsed.component)
            )
        unique: dict[str, JiraIssueSummary] = {}
        for item in listed:
            unique.setdefault(item.key, item)
        return tuple(unique.values())

    def _parse_inventory(self, files: list[tuple[str, str]]) -> list[ParsedTestFile]:
        if not files:
            return []
        reject_duplicate_paths(files)
        remaining = MAX_TEST_FILE_SCENARIOS
        parsed: list[ParsedTestFile] = []
        for path, content in files:
            result = parse_test_file(path, content, self._tags, max_scenarios=remaining)
            remaining -= len(result.scenarios)
            parsed.append(result)
        return parsed

    def _parse(self, arguments: Mapping[str, object]) -> _ParsedArgs:
        if not isinstance(arguments, Mapping):
            raise PullXrayValidationError("arguments must be an object")
        has_story = "story_key" in arguments and arguments["story_key"] is not None
        has_project = arguments.get("project") is True
        if has_story == has_project:
            raise PullXrayValidationError("mutually_exclusive_scope")
        if has_story and "component" in arguments:
            raise PullXrayValidationError("component_on_story_scope")
        story_key = None
        if has_story:
            raw = arguments["story_key"]
            if not isinstance(raw, str) or not raw.strip():
                raise PullXrayValidationError("story_key must be a non-empty string")
            story_key = raw.strip()
        component_explicit_null = "component" in arguments and arguments["component"] is None
        component: str | None
        if has_project:
            if component_explicit_null:
                component = None
            elif "component" not in arguments:
                component = self._default_component
            else:
                raw_c = arguments["component"]
                if not isinstance(raw_c, str) or not raw_c.strip():
                    raise PullXrayValidationError("component must be a non-empty string or null")
                component = raw_c.strip()
        else:
            component = None
        dry_run = arguments.get("dry_run", False)
        if not isinstance(dry_run, bool):
            raise PullXrayValidationError("dry_run must be a boolean")
        formats = _read_formats(arguments.get("formats", ["robot"]))
        files = _read_files_allow_empty(arguments.get("files", []))
        template = self._template
        if "new_file_name_template" in arguments and arguments["new_file_name_template"] is not None:
            raw_t = arguments["new_file_name_template"]
            if not isinstance(raw_t, str) or not raw_t.strip():
                raise PullXrayValidationError("new_file_name_template must be a non-empty string")
            reason = validate_template(raw_t.strip())
            if reason is not None:
                raise PullXrayValidationError(reason)
            template = raw_t.strip()
        new_file_paths = _read_new_file_paths(arguments.get("new_file_paths"))
        return _ParsedArgs(
            story_key=story_key,
            project=has_project,
            component=component,
            files=files,
            formats=formats,
            dry_run=dry_run,
            template=template,
            new_file_paths=new_file_paths,
        )


def _read_new_file_paths(raw: object) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise PullXrayValidationError("new_file_paths must be an object of story_key to path")
    out: dict[str, str] = {}
    for key, path in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise PullXrayValidationError("new_file_paths keys must be non-empty story keys")
        if not isinstance(path, str) or not path.strip():
            raise PullXrayValidationError("new_file_paths values must be non-empty paths")
        if len(path) > MAX_TEST_FILE_PATH_CHARS:
            raise PullXrayValidationError(
                f"path must be at most {MAX_TEST_FILE_PATH_CHARS} characters"
            )
        checked = validate_relative_path(path)
        if isinstance(checked, TargetNamingFailed):
            raise PullXrayValidationError(checked.reason)
        out[key.strip()] = path.strip()
    return out


def _resolve_override_path(
    raw: str,
    *,
    fmt: str,
    story_key: str,
    inventory: Sequence[ParsedTestFile],
    proposed_paths: Mapping[str, str],
) -> str | TargetNamingFailed:
    extension = ".robot" if fmt == "robot" else ".feature"
    other = ".feature" if fmt == "robot" else ".robot"
    stripped = raw.strip().replace("\\", "/")
    if stripped.endswith(other):
        return TargetNamingFailed("wrong_extension")
    resolved = validate_relative_path(stripped, extension=extension)
    if isinstance(resolved, TargetNamingFailed):
        return resolved
    if new_path_collides(resolved, story_key, inventory, proposed_paths):
        return TargetNamingFailed("path_collision")
    return resolved


def _file_level_story(inventory: Sequence[ParsedTestFile], path: str) -> str | None:
    return next((parsed.story_key for parsed in inventory if parsed.path == path), None)


def _approval_titles(parsed: _ParsedArgs) -> list[str]:
    titles: list[str] = []
    if parsed.story_key is not None:
        titles.append(f"story · {parsed.story_key}")
    elif parsed.project:
        label = "project"
        if parsed.component:
            label = f"project · {parsed.component}"
        titles.append(label)
    for path, _ in parsed.files:
        titles.append(f"existing · {path.rsplit('/', 1)[-1]}")
    for story_key, path in parsed.new_file_paths.items():
        titles.append(f"new · {story_key} → {path}")
    if not parsed.new_file_paths and not parsed.files:
        titles.append(f"template · {parsed.template}")
    return titles


def _capped_titles(titles: list[str]) -> tuple[str, ...]:
    shortened = [_shorten_title(item) for item in titles[:MAX_APPROVAL_TITLES]]
    if len(titles) > MAX_APPROVAL_TITLES:
        shortened.append(f"+{len(titles) - MAX_APPROVAL_TITLES} more")
    return tuple(shortened)


def _shorten_title(text: str) -> str:
    if len(text) <= MAX_APPROVAL_TITLE_CHARS:
        return text
    return text[: MAX_APPROVAL_TITLE_CHARS - 1] + "…"


def _read_formats(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise PullXrayValidationError("invalid_formats")
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or item not in _FORMATS or item in seen:
            raise PullXrayValidationError("invalid_formats")
        seen.add(item)
        out.append(item)
    return tuple(out)


def _read_files_allow_empty(files: object) -> list[tuple[str, str]]:
    if not isinstance(files, list):
        raise PullXrayValidationError("files must be a list")
    if len(files) > MAX_TEST_FILES:
        raise TestFileValidationError(None, None, Reason.TOO_MANY_FILES)
    if not files:
        return []
    items: list[tuple[str, str]] = []
    total = 0
    for item in files:
        if not isinstance(item, Mapping) or set(item) != _FILE_KEYS:
            raise PullXrayValidationError("each file must have only path and content")
        path, content = item["path"], item["content"]
        if not isinstance(path, str) or not path.strip():
            raise PullXrayValidationError("path must be a non-empty string")
        if len(path) > MAX_TEST_FILE_PATH_CHARS:
            raise PullXrayValidationError(
                f"path must be at most {MAX_TEST_FILE_PATH_CHARS} characters"
            )
        if not isinstance(content, str):
            raise PullXrayValidationError("content must be a string")
        if not is_supported_test_file(path):
            raise TestFileValidationError(path, None, Reason.UNSUPPORTED_EXTENSION)
        size = len(content.encode("utf-8"))
        if size > MAX_TEST_FILE_BYTES:
            raise TestFileValidationError(path, None, Reason.FILE_TOO_LARGE)
        total += size
        if total > MAX_TEST_FILES_TOTAL_BYTES:
            raise TestFileValidationError(None, None, Reason.TOTAL_TOO_LARGE)
        items.append((path.strip(), content))
    return items


def _payload(
    results: list[_Result],
    files: list[dict[str, object]],
    parsed: _ParsedArgs,
    project_key: str,
) -> str:
    counts = dict.fromkeys(_STATUSES, 0)
    out_results: list[dict[str, object]] = []
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
        out_results.append(
            {
                "key": result.key,
                "summary": result.summary,
                "format": result.format,
                "status": result.status,
                "reason": result.reason,
                "story_key": result.story_key,
                "path": result.path,
                "line": result.line,
                "candidate_keys": list(result.candidate_keys),
                "candidate_identities": list(result.candidate_identities),
                "warnings": list(result.warnings),
            }
        )
    scope: dict[str, object]
    if parsed.story_key is not None:
        scope = {"kind": "story", "story_key": parsed.story_key}
    else:
        scope = {
            "kind": "project",
            "project_key": project_key,
            "component": parsed.component,
        }
    return json.dumps(
        {
            "dry_run": parsed.dry_run,
            "scope": scope,
            "counts": counts,
            "results": out_results,
            "files": files if not parsed.dry_run else [],
        }
    )
