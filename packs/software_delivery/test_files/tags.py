"""Classify raw tags of one scope into Xray test key, story, candidates and plain tags.

A composite tag is a configured marker plus an issue key, in either order.
Robot cells may separate them with whitespace, ``:`` or ``=``; a Gherkin tag is
one whitespace-free token, so only ``:`` or ``=`` apply there. Anything that is
not exactly marker plus key stays whole as a plain tag.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.test_files.models import TagRoles, TestFileTagConfig

TagSyntax = Literal["robot", "gherkin"]
TagScope = Literal["file", "scenario"]

ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*")
_ROBOT_COMPOSITE = re.compile(r"^(\S+?)(?:\s*[:=]\s*|\s+)(\S+)$")
_GHERKIN_COMPOSITE = re.compile(r"^([^:=]+)[:=]([^:=]+)$")
_SINGLE_KEY_ROLES = {
    "xray": Reason.CONFLICTING_XRAY_KEYS,
    "story": Reason.CONFLICTING_STORY_KEYS,
}


def classify(
    tags: Sequence[tuple[int, str]],
    config: TestFileTagConfig,
    syntax: TagSyntax,
    *,
    path: str,
    scope: TagScope,
) -> TagRoles:
    """Split ``(line, tag)`` pairs of one scope into roles, keeping source order.

    Raises:
        TestFileValidationError: Two distinct keys for one role in this scope,
            or an Xray test key at file scope.
    """
    xray: list[str] = []
    story: list[str] = []
    candidates: list[str] = []
    plain: list[str] = []
    for line, tag in tags:
        role, value = _role(tag, config, syntax)
        if role == "xray" and scope == "file":
            raise TestFileValidationError(path, line, Reason.FILE_LEVEL_XRAY_KEY)
        bucket = {"xray": xray, "story": story, "candidate": candidates, "plain": plain}[role]
        if value in bucket:
            continue
        if role in _SINGLE_KEY_ROLES and bucket:
            raise TestFileValidationError(path, line, _SINGLE_KEY_ROLES[role])
        bucket.append(value)
    return TagRoles(
        xray_key=xray[0] if xray else None,
        story_key=story[0] if story else None,
        candidate_keys=tuple(candidates),
        plain=tuple(plain),
    )


def _role(tag: str, config: TestFileTagConfig, syntax: TagSyntax) -> tuple[str, str]:
    if ISSUE_KEY.fullmatch(tag) is not None:
        return "candidate", tag
    pattern = _ROBOT_COMPOSITE if syntax == "robot" else _GHERKIN_COMPOSITE
    match = pattern.match(tag)
    if match is not None:
        first, second = match.group(1), match.group(2)
        for marker, key in ((first, second), (second, first)):
            role = _marker_role(marker, config)
            if role is not None and ISSUE_KEY.fullmatch(key) is not None:
                return role, key
    return "plain", tag


def _marker_role(marker: str, config: TestFileTagConfig) -> str | None:
    folded = marker.casefold()
    if folded == config.test_marker.casefold():
        return "xray"
    if folded == config.story_marker.casefold():
        return "story"
    return None
