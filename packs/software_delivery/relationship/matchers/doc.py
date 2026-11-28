"""``key_mention.doc``: keys mentioned in documents (#375)."""

from __future__ import annotations

from domain.artifact.kinds import ArtifactKind
from domain.relationship.matching import (
    MatchDiagnostic,
    MatchMention,
    MatchOutcome,
    MatchRequest,
)
from packs.software_delivery.relationship.matchers.tag import _known_key_pattern

RULE_ID = "key_mention.doc"
RELATION_TYPE = "describes"


class KeyMentionDocMatcher:
    """Match project keys anywhere in a document artifact."""

    @property
    def rule_id(self) -> str:
        return RULE_ID

    def match(self, request: MatchRequest) -> MatchOutcome:
        if request.subject.kind != ArtifactKind.DOCUMENT:
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
        for match in key_re.finditer(content):
            line = content.count("\n", 0, match.start()) + 1
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
