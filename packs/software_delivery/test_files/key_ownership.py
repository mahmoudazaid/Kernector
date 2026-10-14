"""Validate a write-back call's ``path::scenario`` to Xray key mapping (#399).

Collisions are judged on the final mapping over every file sent, so a key a
scenario gives up in the same call can go to another scenario. Anything the
parser cannot settle without Jira is rejected rather than guessed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.test_files.matching import scenario_identity
from packs.software_delivery.test_files.models import ParsedTestFile, TestFileScenario
from packs.software_delivery.test_files.tags import ISSUE_KEY


def assign_keys(
    files: Sequence[ParsedTestFile], keys: Mapping[str, str]
) -> dict[str, dict[str, str]]:
    """Return ``{path: {summary: key}}`` for the mapped scenarios.

    Raises:
        TestFileValidationError: An unknown file or scenario, a key that is not
            an issue key, two scenarios ending with the same key, or a key
            already used as a story, file-level or other scenario's key tag.
    """
    scenarios = [(parsed, scenario) for parsed in files for scenario in parsed.scenarios]
    identities = {scenario_identity(p.path, s) for p, s in scenarios}
    for identity in keys:
        if identity not in identities:
            path = next((p.path for p in files if identity.startswith(f"{p.path}::")), None)
            reason = Reason.UNKNOWN_FILE if path is None else Reason.UNKNOWN_SCENARIO
            raise TestFileValidationError(path, None, reason)
    assigned = [
        (parsed, scenario, keys[identity])
        for parsed, scenario in scenarios
        if (identity := scenario_identity(parsed.path, scenario)) in keys
    ]
    for parsed, scenario, key in assigned:
        if ISSUE_KEY.fullmatch(key) is None:
            raise TestFileValidationError(parsed.path, scenario.line, Reason.INVALID_XRAY_KEY)
    owners: set[str] = set()
    for parsed, scenario in scenarios:
        final = keys.get(scenario_identity(parsed.path, scenario), scenario.xray_key)
        if final is None:
            continue
        if final in owners:
            raise TestFileValidationError(parsed.path, scenario.line, Reason.DUPLICATE_KEY_OWNER)
        owners.add(final)
    for parsed, scenario, key in assigned:
        if _used_as_other_tag(files, scenario, key):
            raise TestFileValidationError(parsed.path, scenario.line, Reason.KEY_USED_AS_OTHER_TAG)
    result: dict[str, dict[str, str]] = {}
    for parsed, scenario, key in assigned:
        result.setdefault(parsed.path, {})[scenario.summary] = key
    return result


def _used_as_other_tag(
    files: Sequence[ParsedTestFile], scenario: TestFileScenario, key: str
) -> bool:
    """A bare copy on ``scenario`` itself is its own identity, not another use."""
    for parsed in files:
        roles = parsed.file_tags
        if key in (parsed.story_key, roles.story_key) or key in roles.candidate_keys:
            return True
        for other in parsed.scenarios:
            local = other.tags.local
            if other is scenario:
                if key in (local.story_key, scenario.story_key):
                    return True
            elif key == local.story_key or key in local.candidate_keys:
                return True
    return False
