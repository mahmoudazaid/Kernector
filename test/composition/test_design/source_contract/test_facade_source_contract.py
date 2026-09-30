"""Shared contract for every ``TestDesignSource`` at the Test Design facade (#352)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from application.errors import (
    InsufficientEvidenceError,
    SourceItemNotFoundError,
    SourceNotConnectedError,
    SourceReauthorizationRequiredError,
)
from composition.test_design.errors import TestDesignEvidenceChangedError
from composition.test_design.facade import (
    CreateTestDesignDraftRequest,
    GenerateTestDesignCasesRequest,
    PatchTestDesignDraftRequest,
    SourceLocatorView,
    TestCandidateView,
    TestCoverageDraftView,
    TestDesignFacade,
)
from composition.test_design.sources import TestDesignSourceRegistry
from test.composition.test_design.source_contract.harness import SourceContractHarness
from test.composition.test_design.test_design_fakes import (
    FakeTestDesignSource,
    build_fake_facade,
)

_DECOY_PROVIDER = "contract-decoy"


def _facade(
    tmp_path: Path, harness: SourceContractHarness
) -> tuple[TestDesignFacade, FakeTestDesignSource]:
    decoy = FakeTestDesignSource(_DECOY_PROVIDER)
    facade = build_fake_facade(
        tmp_path,
        sources=TestDesignSourceRegistry((harness.source(), decoy)),
    )
    return facade, decoy


def _create(
    facade: TestDesignFacade, harness: SourceContractHarness, locator: str
) -> TestCoverageDraftView:
    return facade.create_draft(
        CreateTestDesignDraftRequest(
            conversation_id="conv-contract",
            source_locator=SourceLocatorView(provider=harness.provider, locator=locator),
        )
    )


def _select_first(
    facade: TestDesignFacade, draft: TestCoverageDraftView
) -> TestCoverageDraftView:
    return facade.patch_draft(
        draft.draft_id,
        PatchTestDesignDraftRequest(
            expected_version=draft.version,
            candidates=tuple(
                TestCandidateView(
                    **{
                        name: getattr(item, name)
                        for name in item.__dataclass_fields__
                        if name != "selected"
                    },
                    selected=index == 0,
                )
                for index, item in enumerate(draft.candidates)
            ),
        ),
    )


def _confirmed(
    facade: TestDesignFacade, harness: SourceContractHarness
) -> TestCoverageDraftView:
    draft = _select_first(facade, _create(facade, harness, harness.canonical_locator))
    return facade.confirm_draft(draft.draft_id, expected_version=draft.version)


def test_create_persists_the_canonical_locator_for_every_raw_form(
    tmp_path: Path, harness: SourceContractHarness
) -> None:
    facade, _decoy = _facade(tmp_path, harness)

    for raw in harness.raw_locators:
        draft = _create(facade, harness, raw)
        assert draft.ticket_identifier == harness.canonical_locator, raw
        assert draft.source_reference.source_type == harness.source_type


_SCENARIOS: dict[str, tuple[Callable[[SourceContractHarness], None], type[Exception]]] = {
    "disconnected": (lambda h: h.disconnect(), SourceNotConnectedError),
    "empty-evidence": (lambda h: h.serve(""), InsufficientEvidenceError),
    "missing-item": (lambda h: h.fail_not_found(), SourceItemNotFoundError),
    "rejected-auth": (lambda h: h.reject_auth(), SourceReauthorizationRequiredError),
}


@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_create_surfaces_only_neutral_source_errors(
    tmp_path: Path, harness: SourceContractHarness, scenario: str
) -> None:
    arrange, expected = _SCENARIOS[scenario]
    facade, decoy = _facade(tmp_path, harness)
    arrange(harness)

    with pytest.raises(expected):
        _create(facade, harness, harness.canonical_locator)

    assert decoy.reader_calls == 0


def test_create_while_disconnected_never_calls_upstream(
    tmp_path: Path, harness: SourceContractHarness
) -> None:
    facade, _decoy = _facade(tmp_path, harness)
    harness.disconnect()

    with pytest.raises(SourceNotConnectedError):
        _create(facade, harness, harness.canonical_locator)

    assert harness.upstream_calls == 0


def test_identity_change_before_confirm_is_evidence_changed(
    tmp_path: Path, harness: SourceContractHarness
) -> None:
    facade, _decoy = _facade(tmp_path, harness)
    draft = _select_first(facade, _create(facade, harness, harness.canonical_locator))
    harness.serve("Acceptance criteria: login, lockout.", item_id="item-2")

    with pytest.raises(TestDesignEvidenceChangedError):
        facade.confirm_draft(draft.draft_id, expected_version=draft.version)

    assert facade.get_draft(draft.draft_id).status == "coverage_review"


def test_content_change_before_generate_is_evidence_changed(
    tmp_path: Path, harness: SourceContractHarness
) -> None:
    facade, _decoy = _facade(tmp_path, harness)
    confirmed = _confirmed(facade, harness)
    harness.serve("Acceptance criteria rewritten after confirmation.")

    with pytest.raises(TestDesignEvidenceChangedError):
        facade.generate_cases(
            confirmed.draft_id,
            GenerateTestDesignCasesRequest(expected_version=confirmed.version),
        )

    assert facade.get_draft(confirmed.draft_id).generated_cases == ()


def test_workflow_refetches_through_the_provider_persisted_at_creation(
    tmp_path: Path, harness: SourceContractHarness
) -> None:
    facade, decoy = _facade(tmp_path, harness)
    confirmed = _confirmed(facade, harness)

    generated = facade.generate_cases(
        confirmed.draft_id,
        GenerateTestDesignCasesRequest(expected_version=confirmed.version),
    )

    assert generated.generated_cases
    assert generated.ticket_identifier == harness.canonical_locator
    assert harness.upstream_calls == 3
    assert decoy.reader_calls == 0
