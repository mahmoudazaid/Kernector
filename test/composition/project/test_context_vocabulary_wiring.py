"""Context vocabulary comes only from allowlisted, enabled packs (#372)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from application.errors import ConfigurationError
from composition.project import vocabulary as vocabulary_module
from composition.project.vocabulary import (
    SUPPORTED_CONTEXT_VOCABULARY_PACKS,
    build_context_vocabulary,
)
from infrastructure.config import DomainToolSettings, load_settings


def _settings(*packs: str):
    return replace(
        load_settings(), domain_tools=DomainToolSettings(enabled_packs=packs)
    )


def test_no_enabled_pack_means_no_vocabulary() -> None:
    assert build_context_vocabulary(_settings()) is None


def test_enabled_software_delivery_pack_registers_its_contexts() -> None:
    vocabulary = build_context_vocabulary(_settings("software-delivery"))

    assert vocabulary is not None
    assert "backend" in vocabulary.contexts
    assert len(vocabulary.contexts) == 7


def test_unlisted_pack_contributes_nothing() -> None:
    assert "other-pack" not in SUPPORTED_CONTEXT_VOCABULARY_PACKS

    assert build_context_vocabulary(_settings("other-pack")) is None


def test_malformed_target_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        vocabulary_module.SUPPORTED_CONTEXT_VOCABULARY_PACKS,
        "software-delivery",
        "no-colon",
    )

    with pytest.raises(ConfigurationError):
        build_context_vocabulary(_settings("software-delivery"))
