"""``key_mention.header``: keys in file headers / module docstrings (#375)."""

from __future__ import annotations

import re

from domain.artifact.kinds import ArtifactKind
from domain.relationship.matching import (
    MatchDiagnostic,
    MatchMention,
    MatchOutcome,
    MatchRequest,
)
from packs.software_delivery.relationship.matchers.tag import _known_key_pattern

RULE_ID = "key_mention.header"
RELATION_TYPE = "references"

# Module docstring or leading block/line comments in the first ~40 lines.
_HEADER_WINDOW_LINES = 40
_DOCSTRING = re.compile(r'(?s)[ruRU]?("""|\'\'\')(.*?)\1')
_LEADING_COMMENTS = re.compile(r"^\s*(?:#|//|/\*|\*)")


def _header_regions(content: str) -> list[tuple[str, int]]:
    """Return (text, 1-based start line) for leading comments and module docstring."""
    lines = content.splitlines()[:_HEADER_WINDOW_LINES]
    regions: list[tuple[str, int]] = []
    index = 0
    if lines and lines[0].startswith("#!"):
        index = 1

    comment_lines: list[str] = []
    comment_start: int | None = None
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            if comment_lines:
                break
            index += 1
            continue
        if _LEADING_COMMENTS.match(line) is None:
            break
        if comment_start is None:
            comment_start = index + 1
        comment_lines.append(line)
        index += 1

    if comment_lines and comment_start is not None:
        regions.append(("\n".join(comment_lines), comment_start))

    while index < len(lines) and not lines[index].strip():
        index += 1

    if index < len(lines):
        remainder = "\n".join(lines[index:])
        doc = _DOCSTRING.match(remainder)
        if doc is not None:
            regions.append((doc.group(2), index + 1))

    return regions


class KeyMentionHeaderMatcher:
    """Match project keys in code_file headers and module docstrings."""

    @property
    def rule_id(self) -> str:
        return RULE_ID

    def match(self, request: MatchRequest) -> MatchOutcome:
        if request.subject.kind != ArtifactKind.CODE_FILE:
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

        mentions: list[MatchMention] = []
        seen: set[tuple[str, str]] = set()
        for text, base_line in _header_regions(content):
            for match in key_re.finditer(text):
                line = base_line + text.count("\n", 0, match.start())
                locator = f"line={line}"
                identity = match.group(0)
                key = (identity, locator)
                if key in seen:
                    continue
                seen.add(key)
                mentions.append(
                    MatchMention(
                        identity=identity,
                        locator=locator,
                        rule_id=RULE_ID,
                        relation_type=RELATION_TYPE,
                    )
                )

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
