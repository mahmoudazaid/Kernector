"""Tests for the source-neutral Test Design source registry (#351)."""

from __future__ import annotations

import pytest

from composition.test_design_errors import (
    TestDesignUnavailableError,
    TestDesignValidationError,
)
from composition.test_design_sources import (
    AmbiguousSourceLocatorError,
    TestDesignSourceRegistry,
)
from domain.knowledge import SourceLocator
from test.composition.test_design_fakes import FakeTestDesignSource


@pytest.mark.parametrize("provider", ["", "   ", None, 7, "gitlab", "not-a-source"])
def test_blank_invalid_or_unknown_provider_is_a_validation_error(
    provider: object,
) -> None:
    registry = TestDesignSourceRegistry((FakeTestDesignSource("acme"),))

    with pytest.raises(TestDesignValidationError):
        registry.resolve(provider)  # type: ignore[arg-type]


@pytest.mark.parametrize("provider", ["jira", "JIRA", "google_drive"])
def test_known_but_unregistered_provider_is_unavailable(provider: str) -> None:
    registry = TestDesignSourceRegistry((FakeTestDesignSource("acme"),))

    with pytest.raises(TestDesignUnavailableError):
        registry.resolve(provider)


def test_registered_provider_resolves_case_insensitively() -> None:
    source = FakeTestDesignSource("acme")
    registry = TestDesignSourceRegistry((source,))

    assert registry.resolve(" ACME ") is source


def test_duplicate_provider_registration_is_rejected() -> None:
    with pytest.raises(ValueError):
        TestDesignSourceRegistry(
            (FakeTestDesignSource("acme"), FakeTestDesignSource("ACME"))
        )


def test_extract_locator_returns_the_single_source_match() -> None:
    registry = TestDesignSourceRegistry(
        (
            FakeTestDesignSource("acme", extracts={"see ACME-1": "ACME-1"}),
            FakeTestDesignSource("other"),
        )
    )

    assert registry.extract_locator("see ACME-1") == SourceLocator("acme", "ACME-1")
    assert registry.extract_locator("nothing here") is None


def test_extract_locator_is_ambiguous_across_sources() -> None:
    registry = TestDesignSourceRegistry(
        (
            FakeTestDesignSource("acme", extracts={"x": "ACME-1"}),
            FakeTestDesignSource("other", extracts={"x": "OTHER-1"}),
        )
    )

    with pytest.raises(AmbiguousSourceLocatorError):
        registry.extract_locator("x")


def test_extract_locator_propagates_source_ambiguity() -> None:
    registry = TestDesignSourceRegistry(
        (FakeTestDesignSource("acme", ambiguous={"two refs"}),)
    )

    with pytest.raises(AmbiguousSourceLocatorError):
        registry.extract_locator("two refs")
