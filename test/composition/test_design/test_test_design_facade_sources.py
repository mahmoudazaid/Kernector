"""Facade and chat handoff resolve live sources through the registry (#351)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.contracts import AskRequest
from composition.test_design.facade import (
    CreateTestDesignDraftRequest,
    GenerateTestDesignCasesRequest,
    SourceLocatorView,
    TestCandidateView,
    build_test_design_handoff_from_request,
)
from composition.test_design.errors import (
    TestDesignUnavailableError,
    TestDesignValidationError,
)
from composition.test_design.sources import TestDesignSourceRegistry
from composition.test_design.store import TEST_DESIGN_NAMESPACE
from domain.knowledge import SourceLocator
from infrastructure.workspace_store.sql_store import VersionedWorkspaceStore
from test.composition.test_design.test_design_fakes import (
    ISSUE_SOURCE_ID,
    FakeTestDesignSource,
    build_fake_facade,
    settings_with_pack,
)


def _registry(*sources: FakeTestDesignSource) -> TestDesignSourceRegistry:
    return TestDesignSourceRegistry(sources)


def _create(facade, provider: str, locator: str):  # noqa: ANN001, ANN202
    return facade.create_draft(
        CreateTestDesignDraftRequest(
            conversation_id="conv-1",
            source_locator=SourceLocatorView(provider=provider, locator=locator),
        )
    )


def _select_first(facade, draft):  # noqa: ANN001, ANN202
    from composition.test_design.facade import PatchTestDesignDraftRequest

    return facade.patch_draft(
        draft.draft_id,
        PatchTestDesignDraftRequest(
            expected_version=draft.version,
            candidates=tuple(
                TestCandidateView(**{**_fields(item), "selected": index == 0})
                for index, item in enumerate(draft.candidates)
            ),
        ),
    )


def _fields(item: TestCandidateView) -> dict[str, object]:
    return {name: getattr(item, name) for name in item.__dataclass_fields__}


@pytest.mark.parametrize("provider", ["", "gitlab"])
def test_unknown_provider_is_rejected_before_any_fetch(
    tmp_path: Path, provider: str
) -> None:
    acme = FakeTestDesignSource("acme")
    facade = build_fake_facade(tmp_path, sources=_registry(acme))

    with pytest.raises(TestDesignValidationError):
        _create(facade, provider, "ACME-1")

    assert acme.reader_calls == 0


def test_known_unregistered_provider_is_unavailable_before_any_fetch(
    tmp_path: Path,
) -> None:
    acme = FakeTestDesignSource("acme")
    facade = build_fake_facade(tmp_path, sources=_registry(acme))

    with pytest.raises(TestDesignUnavailableError):
        _create(facade, "jira", "KERN-1")

    assert acme.reader_calls == 0


def test_create_fetches_canonical_locator_from_the_resolved_source(
    tmp_path: Path,
) -> None:
    acme = FakeTestDesignSource("acme")
    facade = build_fake_facade(tmp_path, sources=_registry(acme))

    draft = _create(facade, "ACME", "  ACME-1 ")

    assert acme.live_reader.calls == [SourceLocator("acme", "ACME-1")]
    assert draft.ticket_identifier == "ACME-1"


def test_confirm_and_generate_refetch_through_the_persisted_provider(
    tmp_path: Path,
) -> None:
    acme = FakeTestDesignSource("acme")
    other = FakeTestDesignSource("other")
    facade = build_fake_facade(tmp_path, sources=_registry(acme, other))
    draft = _select_first(facade, _create(facade, "acme", "ACME-1"))

    confirmed = facade.confirm_draft(draft.draft_id, expected_version=draft.version)
    facade.generate_cases(
        draft.draft_id,
        GenerateTestDesignCasesRequest(expected_version=confirmed.version),
    )

    assert acme.live_reader.calls == [SourceLocator("acme", "ACME-1")] * 3
    assert other.reader_calls == 0


def test_legacy_stored_draft_refetches_through_its_derived_provider(
    tmp_path: Path,
) -> None:
    github = FakeTestDesignSource("github")
    facade = build_fake_facade(tmp_path, sources=_registry(github))
    VersionedWorkspaceStore(tmp_path / "workspace.sqlite", "ws-a").create(
        TEST_DESIGN_NAMESPACE,
        "legacy-1",
        json.dumps(
            {
                "schema_version": 4,
                "workspace_id": "ws-a",
                "conversation_id": "conv-legacy",
                "source_reference": {
                    "source_type": "github",
                    "source_id": ISSUE_SOURCE_ID,
                },
                "ticket_identifier": "acme/app#7",
                "status": "coverage_review",
                "candidates": [
                    {
                        "candidate_id": "cand-1",
                        "title": "Valid login",
                        "category": "positive",
                        "rationale": "Grounded.",
                        "evidence_references": [
                            {"source_type": "github", "source_id": ISSUE_SOURCE_ID}
                        ],
                        "selected": True,
                        "origin": "suggested",
                    }
                ],
            }
        ),
    )

    confirmed = facade.confirm_draft("legacy-1", expected_version=1)

    assert confirmed.status == "ready"
    assert github.live_reader.calls == [SourceLocator("github", "acme/app#7")]


def test_handoff_extracts_the_locator_through_the_registry() -> None:
    query = "Design tests for ACME-1"
    registry = _registry(FakeTestDesignSource("acme", extracts={query: "ACME-1"}))

    handoff = build_test_design_handoff_from_request(
        settings=settings_with_pack(),
        request=AskRequest(query=query),
        sources=registry,
    )

    assert handoff is not None
    assert handoff.action.source_locator == SourceLocatorView("acme", "ACME-1")


def test_handoff_rejects_client_locator_from_another_provider() -> None:
    query = "Design tests for ACME-1"
    registry = _registry(
        FakeTestDesignSource("acme", extracts={query: "ACME-1"}),
        FakeTestDesignSource("other"),
    )

    with pytest.raises(TestDesignValidationError, match="must match"):
        build_test_design_handoff_from_request(
            settings=settings_with_pack(),
            request=AskRequest(query=query),
            source_locator=SourceLocatorView("other", "ACME-1"),
            sources=registry,
        )


def test_handoff_compares_client_locator_after_canonicalization() -> None:
    query = "Design tests for ACME-1"
    registry = _registry(FakeTestDesignSource("acme", extracts={query: "ACME-1"}))

    handoff = build_test_design_handoff_from_request(
        settings=settings_with_pack(),
        request=AskRequest(query=query),
        source_locator=SourceLocatorView("ACME", "  acme-1 "),
        sources=registry,
    )

    assert handoff is not None
