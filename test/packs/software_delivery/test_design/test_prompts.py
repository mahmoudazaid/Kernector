"""Tests for Test Design Markdown prompt templates (ADR 0009)."""

from __future__ import annotations

from importlib.resources import files

import pytest

from packs.software_delivery.test_design import prompts
from packs.software_delivery.test_design.generate_cases import GENERATE_CASES_SYSTEM
from packs.software_delivery.test_design.prompts import load_prompt
from packs.software_delivery.test_design.suggest_tests import (
    CONTEXT_CLOSE,
    CONTEXT_OPEN,
    TEST_CANDIDATE_SUGGESTION_SYSTEM,
)

RENDERED = {
    "generate_cases": GENERATE_CASES_SYSTEM,
    "suggest_tests": TEST_CANDIDATE_SUGGESTION_SYSTEM,
}


def test_every_template_is_rendered_by_a_use_case() -> None:
    templates = {
        entry.name.removesuffix(".md")
        for entry in files(prompts).iterdir()
        if entry.name.endswith(".md")
    }
    assert templates == set(RENDERED)


@pytest.mark.parametrize("name", sorted(RENDERED))
def test_rendered_prompt_carries_context_delimiters(name: str) -> None:
    assert CONTEXT_OPEN in RENDERED[name]
    assert CONTEXT_CLOSE in RENDERED[name]


@pytest.mark.parametrize("name", sorted(RENDERED))
def test_rendered_prompt_has_no_unresolved_placeholder(name: str) -> None:
    assert "$" not in RENDERED[name]


def test_missing_placeholder_value_is_rejected() -> None:
    with pytest.raises(KeyError, match="MAX_SUGGESTED_CANDIDATES"):
        load_prompt(
            "suggest_tests",
            CONTEXT_OPEN=CONTEXT_OPEN,
            CONTEXT_CLOSE=CONTEXT_CLOSE,
        )


def test_unused_value_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"\$UNUSED"):
        load_prompt(
            "generate_cases",
            CONTEXT_OPEN=CONTEXT_OPEN,
            CONTEXT_CLOSE=CONTEXT_CLOSE,
            UNUSED="x",
        )


def test_unknown_template_is_rejected() -> None:
    with pytest.raises(FileNotFoundError):
        load_prompt("does_not_exist")
