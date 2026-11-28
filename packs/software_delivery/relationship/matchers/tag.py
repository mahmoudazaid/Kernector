"""``key_mention.tag``: test tags citing project keys (#375)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from domain.artifact.kinds import ArtifactKind
from domain.relationship.matching import (
    MatchDiagnostic,
    MatchMention,
    MatchOutcome,
    MatchRequest,
)

RULE_ID = "key_mention.tag"
RELATION_TYPE = "automates"

_ROBOT_TAGS = re.compile(
    r"(?im)^(?:\s*\[Tags\]|\s*(?:Default|Force|Test)\s+Tags)\s+(.+)$"
)
_GHERKIN_TAG = re.compile(r"(?m)^\s*(@[^\s]+(?:\s+@[^\s]+)*)\s*$")
_PYTEST_MARK = re.compile(
    r"""(?m)@pytest\.mark\.\w+\(\s*["']([A-Z][A-Z0-9_]*-[1-9][0-9]*)["']\s*\)"""
)
_PLAYWRIGHT_TITLE = re.compile(
    r"""(?m)(?:test|it)\(\s*["']@([A-Z][A-Z0-9_]*-[1-9][0-9]*)\b"""
)


def _known_key_pattern(keys: Iterable[str], prefixes: Iterable[str]) -> re.Pattern[str] | None:
    exact = sorted({re.escape(key) for key in keys if key})
    prefix_parts = sorted({re.escape(prefix) for prefix in prefixes if prefix})
    parts: list[str] = []
    if exact:
        parts.append("|".join(exact))
    if prefix_parts:
        parts.append(
            "(?:%s)-[1-9][0-9]*" % "|".join(prefix_parts)
        )
    if not parts:
        return None
    return re.compile(r"\b(?:%s)\b" % "|".join(parts))


class KeyMentionTagMatcher:
    """Match issue keys in Robot, Gherkin, pytest, and Playwright title tags."""

    @property
    def rule_id(self) -> str:
        return RULE_ID

    def match(self, request: MatchRequest) -> MatchOutcome:
        if request.subject.kind != ArtifactKind.AUTOMATED_TEST:
            return MatchOutcome()
        content = request.content
        byte_len = len(content.encode("utf-8"))
        if byte_len > request.limits.max_content_bytes:
            return MatchOutcome(
                diagnostics=(
                    MatchDiagnostic(
                        code="content_too_large",
                        rule_id=RULE_ID,
                        source=request.source,
                        revision=request.revision,
                        limit=request.limits.max_content_bytes,
                        observed_count=byte_len,
                    ),
                )
            )
        key_re = _known_key_pattern(
            request.key_catalogue.keys, request.key_catalogue.prefixes
        )
        if key_re is None:
            return MatchOutcome()
        pattern_size = len(key_re.pattern.encode("utf-8"))
        if pattern_size > request.limits.max_compiled_pattern_size:
            return MatchOutcome(
                diagnostics=(
                    MatchDiagnostic(
                        code="catalogue_overflow",
                        rule_id=RULE_ID,
                        source=request.source,
                        revision=request.revision,
                        limit=request.limits.max_compiled_pattern_size,
                        observed_count=pattern_size,
                    ),
                )
            )

        mentions: list[MatchMention] = []
        seen: set[tuple[str, str]] = set()

        def _add(identity: str, line: int) -> None:
            locator = f"line={line}"
            key = (identity, locator)
            if key in seen:
                return
            seen.add(key)
            mentions.append(
                MatchMention(
                    identity=identity,
                    locator=locator,
                    rule_id=RULE_ID,
                    relation_type=RELATION_TYPE,
                )
            )

        for match in _ROBOT_TAGS.finditer(content):
            line = content.count("\n", 0, match.start()) + 1
            for key_match in key_re.finditer(match.group(1)):
                _add(key_match.group(0), line)

        for match in _GHERKIN_TAG.finditer(content):
            line = content.count("\n", 0, match.start()) + 1
            for token in match.group(1).split():
                raw = token[1:] if token.startswith("@") else token
                if key_re.fullmatch(raw):
                    _add(raw, line)

        for match in _PYTEST_MARK.finditer(content):
            identity = match.group(1)
            if key_re.fullmatch(identity):
                line = content.count("\n", 0, match.start()) + 1
                _add(identity, line)

        for match in _PLAYWRIGHT_TITLE.finditer(content):
            identity = match.group(1)
            if key_re.fullmatch(identity):
                line = content.count("\n", 0, match.start()) + 1
                _add(identity, line)

        if len(mentions) > request.limits.max_mentions:
            return MatchOutcome(
                diagnostics=(
                    MatchDiagnostic(
                        code="mention_overflow",
                        rule_id=RULE_ID,
                        source=request.source,
                        revision=request.revision,
                        limit=request.limits.max_mentions,
                        observed_count=len(mentions),
                    ),
                )
            )
        return MatchOutcome(mentions=tuple(mentions))
