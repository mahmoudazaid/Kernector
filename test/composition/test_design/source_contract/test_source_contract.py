"""Shared contract every ``TestDesignSource`` adapter must satisfy (#352)."""

from __future__ import annotations

import pytest

from application.errors import (
    InsufficientEvidenceError,
    SourceItemNotFoundError,
    SourceNotConnectedError,
    SourceReauthorizationRequiredError,
)
from composition.test_design.errors import TestDesignValidationError
from domain.knowledge import SourceLocator
from test.composition.test_design.source_contract.harness import SourceContractHarness


def _fetch(harness: SourceContractHarness):  # noqa: ANN202
    source = harness.source()
    return source.reader().fetch(
        SourceLocator(provider=source.provider, locator=harness.canonical_locator)
    )


def test_provider_matches_the_registered_name(harness: SourceContractHarness) -> None:
    assert harness.source().provider == harness.provider


def test_canonicalization_is_idempotent(harness: SourceContractHarness) -> None:
    source = harness.source()

    for raw in harness.raw_locators:
        canonical = source.canonicalize(raw)
        assert canonical == harness.canonical_locator, raw
        assert source.canonicalize(canonical) == canonical


def test_extraction_round_trips_the_canonical_locator(
    harness: SourceContractHarness,
) -> None:
    source = harness.source()

    extracted = source.extract_locator(
        f"Design tests for {harness.canonical_locator} please"
    )

    assert extracted == harness.canonical_locator
    assert source.canonicalize(extracted) == extracted


def test_text_without_a_locator_extracts_nothing(harness: SourceContractHarness) -> None:
    assert harness.source().extract_locator("Design tests for the login page") is None


def test_invalid_locators_are_validation_errors(harness: SourceContractHarness) -> None:
    source = harness.source()

    for invalid in harness.invalid_locators:
        with pytest.raises(TestDesignValidationError):
            source.canonicalize(invalid)


def test_fetch_returns_a_stable_source_document(harness: SourceContractHarness) -> None:
    first = _fetch(harness)
    again = _fetch(harness)

    assert first.reference.source_type == harness.source_type
    assert first.reference.source_id.strip()
    assert first.content.strip()
    assert again.reference == first.reference


def test_distinct_items_have_distinct_references(harness: SourceContractHarness) -> None:
    first = _fetch(harness)
    harness.serve("Other acceptance criteria.", item_id="item-2")

    second = _fetch(harness)

    assert second.reference != first.reference


def test_disconnected_source_never_calls_upstream(harness: SourceContractHarness) -> None:
    harness.disconnect()

    with pytest.raises(SourceNotConnectedError):
        harness.source().reader()

    assert harness.upstream_calls == 0


@pytest.mark.parametrize("body", ["", "   \n\t"])
def test_empty_evidence_is_insufficient(
    harness: SourceContractHarness, body: str
) -> None:
    harness.serve(body)

    with pytest.raises(InsufficientEvidenceError):
        _fetch(harness)


def test_missing_item_is_source_item_not_found(harness: SourceContractHarness) -> None:
    harness.fail_not_found()

    with pytest.raises(SourceItemNotFoundError):
        _fetch(harness)


def test_rejected_credentials_require_reauthorization(
    harness: SourceContractHarness,
) -> None:
    harness.reject_auth()

    with pytest.raises(SourceReauthorizationRequiredError) as raised:
        _fetch(harness)

    assert not isinstance(raised.value, SourceNotConnectedError)


def test_after_rejection_the_source_stays_reauth_without_calling_upstream(
    harness: SourceContractHarness,
) -> None:
    harness.reject_auth()
    with pytest.raises(SourceReauthorizationRequiredError):
        _fetch(harness)
    calls = harness.upstream_calls

    with pytest.raises(SourceReauthorizationRequiredError):
        harness.source().reader()

    assert harness.upstream_calls == calls
