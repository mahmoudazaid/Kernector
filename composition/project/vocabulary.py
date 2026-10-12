"""Load project context vocabularies from allowlisted, enabled packs."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from dataclasses import dataclass

from application.errors import ConfigurationError
from domain.project.ports import ContextVocabulary
from infrastructure.config import Settings

SUPPORTED_CONTEXT_VOCABULARY_PACKS: dict[str, str] = {
    "software-delivery": "packs.software_delivery.registration:build_context_vocabulary",
}


@dataclass(frozen=True, slots=True)
class _CombinedVocabulary:
    contexts: tuple[str, ...]


def build_context_vocabulary(
    settings: Settings,
    *,
    supported: Mapping[str, str] | None = None,
) -> ContextVocabulary | None:
    """Return the enabled packs' contexts in pack order, or ``None`` when none.

    Pack modules are imported only when their id is in
    ``settings.domain_tools.enabled_packs``.
    """
    targets = SUPPORTED_CONTEXT_VOCABULARY_PACKS if supported is None else supported
    contexts: list[str] = []
    for pack_id in settings.domain_tools.enabled_packs:
        target = targets.get(pack_id)
        if target is None:
            continue
        module_name, _, attr = target.partition(":")
        if not module_name or not attr:
            raise ConfigurationError("invalid context vocabulary pack target")
        vocabulary = getattr(importlib.import_module(module_name), attr)()
        contexts.extend(c for c in vocabulary.contexts if c not in contexts)
    return _CombinedVocabulary(tuple(contexts)) if contexts else None
