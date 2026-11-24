"""Classify artifact contexts from pack rules over structural facts."""

from __future__ import annotations

from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import PurePosixPath

from domain.artifact.facts import ArtifactStructuralFacts
from domain.artifact.models import ContextAssignment
from domain.artifact.rules import ContextClassificationRule, ContextRuleMode

REASON_ROLE_DEFAULT = "role_default"
REASON_ROLE_DEFAULT_AMBIGUOUS = "role_default_ambiguous"


def _path_matches(path: str, filename: str, patterns: Sequence[str]) -> bool:
    if not patterns:
        return False
    posix = path.replace("\\", "/")
    name = filename or PurePosixPath(posix).name
    return any(
        fnmatch(posix, pattern) or fnmatch(name, pattern) for pattern in patterns
    )


def _rule_matches(
    rule: ContextClassificationRule, facts: ArtifactStructuralFacts
) -> bool:
    if rule.require_valid_spec_root and not facts.valid_spec_root:
        return False
    checks: list[bool] = []
    if rule.provider_type_fields:
        checks.append(facts.provider_type_field in rule.provider_type_fields)
    if rule.path_globs or rule.filename_globs:
        checks.append(
            _path_matches(
                facts.path,
                facts.filename,
                (*rule.path_globs, *rule.filename_globs),
            )
        )
    if rule.require_valid_spec_root and not (
        rule.provider_type_fields or rule.path_globs or rule.filename_globs
    ):
        return True
    return all(checks) if checks else False


def _with_role_defaults(
    by_context: dict[str, ContextAssignment], facts: ArtifactStructuralFacts
) -> dict[str, ContextAssignment]:
    for _prefix, role in facts.path_prefix_roles:
        by_context.setdefault(role, ContextAssignment(role, REASON_ROLE_DEFAULT))
    for role in facts.association_roles:
        by_context.setdefault(role, ContextAssignment(role, REASON_ROLE_DEFAULT))
    return by_context


def classify_contexts(
    facts: ArtifactStructuralFacts,
    rules: Sequence[ContextClassificationRule],
) -> tuple[ContextAssignment, ...]:
    """Apply pack rules over facts; fall back to association roles when needed."""
    by_context: dict[str, ContextAssignment] = {}
    any_replace = False
    matched = False
    for rule in rules:
        if not _rule_matches(rule, facts):
            continue
        matched = True
        assignment = ContextAssignment(rule.context, rule.rule_id)
        if rule.mode is ContextRuleMode.REPLACE:
            by_context = {assignment.context: assignment}
            any_replace = True
        else:
            by_context.setdefault(assignment.context, assignment)
    if matched:
        if not any_replace:
            by_context = _with_role_defaults(by_context, facts)
        else:
            # REPLACE clears role defaults, but path-prefix roles still apply
            # when they add a distinct monorepo context (e.g. backend).
            for _prefix, role in facts.path_prefix_roles:
                by_context.setdefault(
                    role, ContextAssignment(role, REASON_ROLE_DEFAULT)
                )
        return tuple(by_context.values())

    roles = list(facts.association_roles)
    for _prefix, role in facts.path_prefix_roles:
        if role not in roles:
            roles.append(role)
    if not roles:
        return ()
    if len(roles) == 1:
        return (ContextAssignment(roles[0], REASON_ROLE_DEFAULT),)
    return (ContextAssignment(roles[0], REASON_ROLE_DEFAULT_AMBIGUOUS),)
