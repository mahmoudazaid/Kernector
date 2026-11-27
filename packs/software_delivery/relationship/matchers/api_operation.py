"""``api_operation.mention``: operationId or METHOD /path mentions (#375)."""

from __future__ import annotations

import re

from domain.relationship.api_paths import normalize_method_path
from domain.relationship.matching import (
    MatchDiagnostic,
    MatchMention,
    MatchOutcome,
    MatchRequest,
)

RULE_ID = "api_operation.mention"

_METHOD_PATH = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD|TRACE)\s+([/`']?/?(?:[^\s`'\"<>]+))"
)
_FETCH_PATH = re.compile(
    r"""fetch\(\s*[`'"]([^`'"]+)[`'"]\s*(?:,\s*\{[^}]*method\s*:\s*["'](\w+)["'])?""",
    re.IGNORECASE | re.DOTALL,
)


class ApiOperationMentionMatcher:
    """Match current API operations by operationId or normalized METHOD /path."""

    @property
    def rule_id(self) -> str:
        return RULE_ID

    def match(self, request: MatchRequest) -> MatchOutcome:
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

        by_op_id = {
            entry.operation_id: entry
            for entry in request.api_operations
            if entry.operation_id
        }
        by_method_path = {
            entry.method_path: entry
            for entry in request.api_operations
            if entry.method_path
        }

        mentions: list[MatchMention] = []
        diagnostics: list[MatchDiagnostic] = []
        seen: set[tuple[str, str]] = set()

        def _add(identity: str, line: int, *, resolved: bool) -> None:
            locator = f"line={line}"
            key = (identity, locator)
            if key in seen:
                return
            seen.add(key)
            if not resolved:
                diagnostics.append(
                    MatchDiagnostic(
                        code="unresolved_operation",
                        rule_id=RULE_ID,
                        source=request.source,
                        revision=request.revision,
                        locator=locator,
                    )
                )
                return
            mentions.append(
                MatchMention(
                    identity=identity,
                    locator=locator,
                    rule_id=RULE_ID,
                    relation_type=None,
                )
            )

        # operationId bare mentions
        for op_id in by_op_id:
            for match in re.finditer(rf"\b{re.escape(op_id)}\b", content):
                line = content.count("\n", 0, match.start()) + 1
                _add(op_id, line, resolved=True)

        # Explicit METHOD path
        for match in _METHOD_PATH.finditer(content):
            method, raw_path = match.group(1), match.group(2)
            identity = normalize_method_path(method, raw_path)
            line = content.count("\n", 0, match.start()) + 1
            entry = by_method_path.get(identity)
            if entry is None:
                _add(identity, line, resolved=False)
            else:
                _add(entry.operation_id or identity, line, resolved=True)

        # fetch(`/path`, { method: "POST" })
        for match in _FETCH_PATH.finditer(content):
            raw_path, method = match.group(1), match.group(2) or "GET"
            identity = normalize_method_path(method, raw_path)
            line = content.count("\n", 0, match.start()) + 1
            entry = by_method_path.get(identity)
            if entry is None:
                # Also try normalized catalogue keys built from caller form
                resolved = False
                for method_path, candidate in by_method_path.items():
                    if method_path == identity:
                        _add(
                            candidate.operation_id or method_path,
                            line,
                            resolved=True,
                        )
                        resolved = True
                        break
                if not resolved:
                    _add(identity, line, resolved=False)
            else:
                _add(entry.operation_id or identity, line, resolved=True)

        if len(mentions) + len(diagnostics) > request.limits.max_mentions:
            return MatchOutcome(
                diagnostics=(
                    MatchDiagnostic(
                        code="mention_overflow",
                        rule_id=RULE_ID,
                        source=request.source,
                        revision=request.revision,
                        limit=request.limits.max_mentions,
                        observed_count=len(mentions) + len(diagnostics),
                    ),
                )
            )
        return MatchOutcome(
            mentions=tuple(mentions), diagnostics=tuple(diagnostics)
        )
