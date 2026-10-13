"""Match untagged file scenarios to existing Xray tests and parent stories (#397, #398).

One implementation shared by the create (#397) and update (#398) tools. It is
pure over the parsed files, the key lookup and the linked tests per story; the
caller performs every Jira read before any write.

Rules, in order, for each scenario without an Xray key:

1. Bare issue keys on the scenario. A missing or unresolved key stops the
   scenario. One unclaimed Test key is the existing test; a claimed one is an
   error; several Test keys are ambiguous. A Test key is never a story.
2. The parent story is chosen and verified against the configured story
   issue types.
3. A test linked to that story whose summary is exactly the scenario summary.
   Keys claimed by tagged scenarios are skipped. Keys claimed by, or tests
   planned for, an earlier scenario in the run make the scenario ambiguous so
   one summary is never created twice.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from domain.test_management.xray import IssueLookupResult, JiraIssueSummary
from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.test_files.models import ParsedTestFile, TestFileScenario

MatchStatus = Literal["CREATE", "EXISTS_UNTAGGED", "AMBIGUOUS", "NO_STORY", "ERROR"]
LinkedTests = Callable[[str], Sequence[JiraIssueSummary]]


@dataclass(frozen=True, slots=True)
class ScenarioMatch:
    """Plan entry for one untagged scenario; ``CREATE`` means no existing test matched.

    ``repeat_of`` names the earlier scenario planned for creation with the same
    story and summary, so the caller can report the key it creates.
    """

    path: str
    scenario: TestFileScenario
    status: MatchStatus
    key: str | None = None
    candidate_keys: tuple[str, ...] = ()
    story_key: str | None = None
    reason: str | None = None
    repeat_of: str | None = None

    @property
    def identity(self) -> str:
        return scenario_identity(self.path, self.scenario)


@dataclass(slots=True)
class _RunClaims:
    tagged: frozenset[str]
    matched: set[str] = field(default_factory=set)
    planned: dict[tuple[str, str], str] = field(default_factory=dict)

    def taken(self, key: str) -> bool:
        return key in self.tagged or key in self.matched


def scenario_identity(path: str, scenario: TestFileScenario) -> str:
    return f"{path}::{scenario.summary}"


def untagged(files: Iterable[ParsedTestFile]) -> list[tuple[ParsedTestFile, TestFileScenario]]:
    return [(f, s) for f in files for s in f.scenarios if s.xray_key is None]


def reject_duplicate_identities(files: Iterable[ParsedTestFile]) -> None:
    """Raise when two untagged scenarios share ``path::summary``.

    Raises:
        TestFileValidationError: Names the second scenario's file and line.
    """
    seen: set[str] = set()
    for parsed, scenario in untagged(files):
        identity = scenario_identity(parsed.path, scenario)
        if identity in seen:
            raise TestFileValidationError(
                parsed.path, scenario.line, Reason.DUPLICATE_SCENARIO_SUMMARY
            )
        seen.add(identity)


def lookup_keys(files: Iterable[ParsedTestFile]) -> tuple[str, ...]:
    """Every key the matcher may resolve: bare scenario keys and story candidates."""
    keys: list[str] = []
    for _file, scenario in untagged(files):
        local = scenario.tags.local
        keys.extend(local.candidate_keys)
        keys.extend(k for k in (local.story_key, scenario.story_key) if k is not None)
    return tuple(dict.fromkeys(keys))


def match_scenarios(
    files: Sequence[ParsedTestFile],
    issues: IssueLookupResult,
    *,
    linked_tests: LinkedTests,
    story_issue_types: frozenset[str],
) -> tuple[ScenarioMatch, ...]:
    """Plan every untagged scenario in file and line order."""
    story_types = frozenset(t.casefold() for t in story_issue_types)
    claims = _RunClaims(
        tagged=frozenset(s.xray_key for f in files for s in f.scenarios if s.xray_key)
    )
    matches: list[ScenarioMatch] = []
    for parsed, scenario in untagged(files):
        match = _match(parsed, scenario, issues, linked_tests, story_types, claims)
        if match.status == "EXISTS_UNTAGGED" and match.key is not None:
            claims.matched.add(match.key)
        elif match.status == "CREATE" and match.story_key is not None:
            claims.planned[(match.story_key, scenario.summary)] = match.identity
        matches.append(match)
    return tuple(matches)


def _match(
    parsed: ParsedTestFile,
    scenario: TestFileScenario,
    issues: IssueLookupResult,
    linked_tests: LinkedTests,
    story_types: frozenset[str],
    claims: _RunClaims,
) -> ScenarioMatch:
    def result(status: MatchStatus, **values: object) -> ScenarioMatch:
        return ScenarioMatch(parsed.path, scenario, status, **values)  # type: ignore[arg-type]

    bare = scenario.tags.local.candidate_keys
    for key in bare:
        if key not in issues.found:
            reason = "issue_not_found" if key in issues.missing else "issue_unresolved"
            return result("ERROR", key=key, reason=reason)
    tests = [key for key in bare if issues.found[key].is_test]
    if len(tests) > 1:
        return result("AMBIGUOUS", candidate_keys=tuple(tests), reason="multiple_tests")
    if tests:
        if claims.taken(tests[0]):
            return result("ERROR", key=tests[0], reason="test_key_claimed")
        return result("EXISTS_UNTAGGED", key=tests[0])

    story, problem = _story(parsed, scenario, issues, story_types)
    if problem is not None:
        status, reason = problem
        return result(status, story_key=story, reason=reason)
    assert story is not None

    same = [
        test.key
        for test in linked_tests(story)
        if test.summary == scenario.summary and test.key not in claims.tagged
    ]
    free = [key for key in same if key not in claims.matched]
    if len(free) > 1:
        return result(
            "AMBIGUOUS", candidate_keys=tuple(free), story_key=story, reason="multiple_tests"
        )
    if free:
        return result("EXISTS_UNTAGGED", key=free[0], story_key=story)
    repeat_of = claims.planned.get((story, scenario.summary))
    if same or repeat_of is not None:
        return result(
            "AMBIGUOUS",
            candidate_keys=tuple(same),
            story_key=story,
            reason="repeated_in_run",
            repeat_of=repeat_of,
        )
    return result("CREATE", story_key=story)


def _story(
    parsed: ParsedTestFile,
    scenario: TestFileScenario,
    issues: IssueLookupResult,
    story_types: frozenset[str],
) -> tuple[str | None, tuple[MatchStatus, str] | None]:
    local = scenario.tags.local
    if parsed.format == "robot":
        chosen = local.story_key or next(iter(local.candidate_keys), None) or scenario.story_key
    else:
        chosen = scenario.story_key
    if chosen is None:
        return None, ("NO_STORY", "no_story")
    if chosen in issues.missing:
        return chosen, ("NO_STORY", "story_not_found")
    issue = issues.found.get(chosen)
    if issue is None:
        return chosen, ("ERROR", "story_unresolved")
    if issue.is_test or not _is_story(issue, story_types):
        return chosen, ("NO_STORY", "not_a_story")
    return chosen, None


def _is_story(issue: JiraIssueSummary, story_types: frozenset[str]) -> bool:
    return (
        issue.issue_type_name.casefold() in story_types
        or issue.issue_type_id.casefold() in story_types
    )
