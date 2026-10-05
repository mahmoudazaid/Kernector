"""Tests for the source-neutral Test Design source registry (#351)."""

from __future__ import annotations

import pytest

from composition.test_design.errors import (
    TestDesignUnavailableError,
    TestDesignValidationError,
    UnsupportedSourceLocatorError,
)
from composition.test_design.sources import (
    AmbiguousSourceLocatorError,
    TestDesignSourceRegistry,
)
from domain.knowledge import SourceLocator
from test.composition.test_design.test_design_fakes import FakeTestDesignSource


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


def test_providers_lists_registered_keys_in_registration_order() -> None:
    registry = TestDesignSourceRegistry(
        (FakeTestDesignSource("github"), FakeTestDesignSource("jira"))
    )

    assert registry.providers == ("github", "jira")


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


def _hash_locators(locator: str) -> bool:
    return "#" in locator


def _dash_locators(locator: str) -> bool:
    return "-" in locator


def test_resolve_locator_returns_the_single_accepting_source() -> None:
    registry = TestDesignSourceRegistry(
        (
            FakeTestDesignSource("acme", accepts=_hash_locators),
            FakeTestDesignSource("other", accepts=_dash_locators),
        )
    )

    assert registry.resolve_locator(" OTHER-1 ") == SourceLocator("other", "OTHER-1")


def test_resolve_locator_without_an_accepting_source_is_unsupported() -> None:
    registry = TestDesignSourceRegistry(
        (
            FakeTestDesignSource("acme", accepts=_hash_locators),
            FakeTestDesignSource("other", accepts=_dash_locators),
        )
    )

    with pytest.raises(UnsupportedSourceLocatorError) as raised:
        registry.resolve_locator("plain words")

    assert isinstance(raised.value, TestDesignValidationError)


def test_resolve_locator_accepted_by_several_sources_is_ambiguous() -> None:
    registry = TestDesignSourceRegistry(
        (
            FakeTestDesignSource("acme", accepts=_dash_locators),
            FakeTestDesignSource("other", accepts=_dash_locators),
        )
    )

    with pytest.raises(TestDesignValidationError, match="ambiguous") as raised:
        registry.resolve_locator("X-1")

    assert not isinstance(raised.value, UnsupportedSourceLocatorError)


def test_resolve_locator_propagates_operational_errors_while_probing() -> None:
    failure = RuntimeError("credential store unreadable")
    registry = TestDesignSourceRegistry(
        (
            FakeTestDesignSource("acme", canonicalize_error=failure),
            FakeTestDesignSource("other", accepts=_dash_locators),
        )
    )

    with pytest.raises(RuntimeError) as raised:
        registry.resolve_locator("OTHER-1")

    assert raised.value is failure


def test_extract_locator_propagates_source_ambiguity() -> None:
    registry = TestDesignSourceRegistry(
        (FakeTestDesignSource("acme", ambiguous={"two refs"}),)
    )

    with pytest.raises(AmbiguousSourceLocatorError):
        registry.extract_locator("two refs")
