"""Opaque context-classification rule contracts (no context literals)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ContextRuleMode(StrEnum):
    ADD = "add"
    REPLACE = "replace"


@dataclass(frozen=True, slots=True)
class ContextClassificationRule:
    """Pack-supplied rule; ``context`` is opaque data registered by the pack."""

    rule_id: str
    context: str
    mode: ContextRuleMode = ContextRuleMode.ADD
    provider_type_fields: tuple[str, ...] = ()
    path_globs: tuple[str, ...] = ()
    filename_globs: tuple[str, ...] = ()
    require_valid_spec_root: bool = False
