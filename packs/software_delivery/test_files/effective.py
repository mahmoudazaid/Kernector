"""Combine inherited (file-scope) and local (scenario-scope) tag roles."""

from __future__ import annotations

from dataclasses import dataclass, replace

from packs.software_delivery.test_files.models import (
    ScenarioKind,
    ScenarioTags,
    TagRoles,
    TestFileTagConfig,
)


@dataclass(frozen=True, slots=True)
class EffectiveTags:
    tags: ScenarioTags
    kind: ScenarioKind
    story_key: str | None
    xray_key: str | None


def effective_tags(
    *,
    file_roles: TagRoles,
    inherited_plain: tuple[str, ...],
    file_story: str | None,
    local: TagRoles,
    config: TestFileTagConfig,
) -> EffectiveTags:
    """A local ``Story`` key overrides the file story; it is never a conflict."""
    plain = tuple(dict.fromkeys((*inherited_plain, *local.plain)))
    manual = {tag.casefold() for tag in config.manual_tags}
    kind: ScenarioKind = (
        "manual" if any(tag.casefold() in manual for tag in plain) else "cucumber"
    )
    return EffectiveTags(
        tags=ScenarioTags(
            inherited=replace(file_roles, plain=inherited_plain),
            local=local,
            effective_plain=plain,
        ),
        kind=kind,
        story_key=local.story_key or file_story,
        xray_key=local.xray_key,
    )


def file_story(roles: TagRoles) -> str | None:
    """Explicit file ``Story`` key, else the single bare key; never a guess."""
    if roles.story_key is not None:
        return roles.story_key
    if len(roles.candidate_keys) == 1:
        return roles.candidate_keys[0]
    return None
