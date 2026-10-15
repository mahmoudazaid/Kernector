"""Resolve the parent story of an Xray test from its issue links (#400)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from domain.test_management.xray import (
    IssueLinkDirection,
    IssueLookupResult,
    JiraIssueSummary,
    XrayTestDetails,
)

ParentStatus = Literal[
    "ok",
    "skip_no_story",
    "story_unresolved",
    "story_missing",
    "story_not_qualifying",
    "story_ambiguous",
    "story_link_unconfirmed",
]


@dataclass(frozen=True, slots=True)
class ParentStory:
    status: ParentStatus
    story_key: str | None = None
    candidate_keys: tuple[str, ...] = ()


FindIssues = Callable[[Sequence[str]], IssueLookupResult]


def resolve_parent(
    details: XrayTestDetails,
    *,
    link_type: str,
    link_direction: IssueLinkDirection,
    story_issue_types: frozenset[str],
    find_issues: FindIssues,
    required_story_key: str | None = None,
) -> ParentStory:
    """Pick the single qualifying parent story, or a precise failure status."""
    typed = [
        link.issue_key
        for link in details.links
        if link.type_name == link_type and link.direction == link_direction
    ]
    if required_story_key is not None:
        if required_story_key not in typed:
            return ParentStory("story_link_unconfirmed", candidate_keys=tuple(typed))
        typed = [required_story_key]

    if not typed:
        return ParentStory("skip_no_story")

    lookup = find_issues(typed)
    qualifying: list[str] = []
    missing: list[str] = []
    not_qualifying: list[str] = []
    unresolved: list[str] = []
    for key in typed:
        if key in lookup.missing:
            missing.append(key)
            continue
        issue = lookup.found.get(key)
        if issue is None:
            unresolved.append(key)
            continue
        if _is_story(issue, story_issue_types):
            qualifying.append(key)
        else:
            not_qualifying.append(key)

    if unresolved:
        return ParentStory("story_unresolved", candidate_keys=tuple(unresolved))
    if len(qualifying) > 1:
        return ParentStory("story_ambiguous", candidate_keys=tuple(qualifying))
    if len(qualifying) == 1:
        return ParentStory("ok", story_key=qualifying[0])
    if missing and not not_qualifying:
        return ParentStory("story_missing", candidate_keys=tuple(missing))
    if not_qualifying and not missing:
        return ParentStory("story_not_qualifying", candidate_keys=tuple(not_qualifying))
    if missing:
        return ParentStory("story_missing", candidate_keys=tuple(missing))
    return ParentStory("skip_no_story")


def validate_scope_story(
    story_key: str,
    *,
    story_issue_types: frozenset[str],
    find_issues: FindIssues,
) -> ParentStatus | None:
    """Return a failure status when ``story_key`` is not a usable story, else ``None``."""
    lookup = find_issues([story_key])
    if story_key in lookup.missing:
        return "story_missing"
    issue = lookup.found.get(story_key)
    if issue is None:
        return "story_unresolved"
    if not _is_story(issue, story_issue_types):
        return "story_not_qualifying"
    return None


def _is_story(issue: JiraIssueSummary, story_issue_types: frozenset[str]) -> bool:
    allowed = {item.casefold() for item in story_issue_types}
    return (
        issue.issue_type_name.casefold() in allowed
        or issue.issue_type_id.casefold() in allowed
    )


def known_xray_keys(parsed_files: Sequence) -> frozenset[str]:
    keys: set[str] = set()
    for parsed in parsed_files:
        for scenario in parsed.scenarios:
            if scenario.xray_key:
                keys.add(scenario.xray_key)
    return frozenset(keys)


def inventory_matches(
    parsed_files: Sequence,
    *,
    story_key: str,
    fmt: str,
    summary: str,
) -> list[tuple[str, object]]:
    """Local scenarios matching story+format+summary across the inventory."""
    wanted = "robot" if fmt == "robot" else "gherkin"
    hits: list[tuple[str, object]] = []
    for parsed in parsed_files:
        if parsed.format != wanted:
            continue
        for scenario in parsed.scenarios:
            if scenario.summary != summary:
                continue
            scenario_story = scenario.story_key or parsed.story_key
            if scenario_story == story_key:
                hits.append((parsed.path, scenario))
    return hits
