"""Suggest associations only from authoritative provider-declared evidence (#372).

Fixture-only: no production source supplies this evidence yet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from application.project.associations import (
    ConfirmAssociation,
    ConfirmAssociationRequest,
)
from application.project.suggest import SuggestAssociations
from domain.knowledge import SourceReference
from domain.project.errors import SharedScopeConfirmationRequiredError
from domain.project.models import (
    AssociationEvidence,
    AssociationState,
    Project,
    SourceAssociation,
    SourceScope,
)
from test.application.project.project_fakes import InMemoryProjectStore, confirmed


@dataclass(frozen=True)
class _Vocabulary:
    contexts: tuple[str, ...] = ("documentation",)


PROJ_JIRA = SourceScope("jira-1", "project_key", "PROJ")
PAY_JIRA = SourceScope("jira-1", "project_key", "PAY")
PROJ_DOCS = SourceScope("gh-1", "repo", "acme/proj-docs")
PROJ_WEB = SourceScope("gh-1", "repo", "acme/proj-web")
PAY_WEB = SourceScope("gh-1", "repo", "acme/pay-web")
REMOTE_LINK = SourceReference("cloud-abc/PROJ:PROJ-123", "jira")


@dataclass
class FixtureEvidence:
    items: Sequence[AssociationEvidence]

    def evidence(self) -> Sequence[AssociationEvidence]:
        return self.items


def _evidence(
    source: SourceScope = PROJ_JIRA,
    target: SourceScope = PROJ_DOCS,
    reference: SourceReference = REMOTE_LINK,
) -> AssociationEvidence:
    return AssociationEvidence(source, target, reference, "field=remotelinks")


@pytest.fixture
def store() -> InMemoryProjectStore:
    store = InMemoryProjectStore()
    with store.transaction() as tx:
        tx.projects.add(Project("prj_proj", "PROJ", "proj", 1))
        tx.projects.add(Project("prj_pay", "PAY", "pay", 1))
        tx.associations.add(confirmed("prj_proj", PROJ_JIRA, ("business",)))
        tx.associations.add(confirmed("prj_proj", PROJ_WEB, ("frontend",)))
        tx.associations.add(confirmed("prj_pay", PAY_JIRA, ("business",)))
    return store


def _suggest(
    store: InMemoryProjectStore, *items: AssociationEvidence
) -> tuple[SourceAssociation, ...]:
    return SuggestAssociations(store=store, evidence=FixtureEvidence(items)).execute()


def test_authoritative_evidence_produces_a_cited_suggestion(
    store: InMemoryProjectStore,
) -> None:
    second = SourceReference("cloud-abc/PROJ:PROJ-140", "jira")

    suggestions = _suggest(store, _evidence(), _evidence(reference=second))

    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert (suggestion.project_id, suggestion.scope) == ("prj_proj", PROJ_DOCS)
    assert suggestion.state is AssociationState.SUGGESTED
    assert suggestion.evidence == (REMOTE_LINK, second)
    with store.read() as tx:
        assert tx.associations.get("prj_proj", PROJ_DOCS) == suggestion


def test_new_repository_without_evidence_gets_no_suggestion(
    store: InMemoryProjectStore,
) -> None:
    assert _suggest(store) == ()
    with store.read() as tx:
        assert tx.associations.for_scope(PAY_WEB) == ()


def test_name_similarity_alone_never_suggests(store: InMemoryProjectStore) -> None:
    unrelated = AssociationEvidence(
        PAY_JIRA, PAY_WEB, SourceReference("cloud-abc/PAY:PAY-1", "jira"), "f=x"
    )

    suggestions = _suggest(store, unrelated)

    assert [(s.project_id, s.scope) for s in suggestions] == [("prj_pay", PAY_WEB)]
    with store.read() as tx:
        assert tx.associations.get("prj_proj", PAY_WEB) is None


def test_evidence_from_an_unconfirmed_source_scope_is_ignored(
    store: InMemoryProjectStore,
) -> None:
    orphan = SourceScope("jira-1", "project_key", "OPS")

    assert _suggest(store, _evidence(source=orphan)) == ()


@pytest.mark.parametrize(
    "state", [AssociationState.CONFIRMED, AssociationState.REJECTED]
)
def test_suggestion_never_overrides_an_operator_decision(
    store: InMemoryProjectStore, state: AssociationState
) -> None:
    decided = SourceAssociation(
        "prj_proj", PROJ_DOCS, ("documentation",), state, (), "operator", 4
    )
    with store.transaction() as tx:
        tx.associations.add(decided)

    assert _suggest(store, _evidence()) == ()
    with store.read() as tx:
        assert tx.associations.get("prj_proj", PROJ_DOCS) == decided


def test_repeated_run_does_not_duplicate_a_suggestion(
    store: InMemoryProjectStore,
) -> None:
    _suggest(store, _evidence())

    assert _suggest(store, _evidence()) == ()


def test_confirming_a_suggestion_for_a_shared_scope_needs_acknowledgement(
    store: InMemoryProjectStore,
) -> None:
    with store.transaction() as tx:
        tx.associations.add(confirmed("prj_pay", PROJ_DOCS, ("documentation",)))
    (suggestion,) = _suggest(store, _evidence())
    confirm = ConfirmAssociation(store=store, vocabulary=_Vocabulary())

    with pytest.raises(SharedScopeConfirmationRequiredError) as raised:
        confirm.execute(
            ConfirmAssociationRequest(
                "prj_proj", PROJ_DOCS, expected_version=suggestion.version
            )
        )

    assert raised.value.project_ids == ("prj_pay",)
    with store.read() as tx:
        assert tx.associations.get("prj_proj", PROJ_DOCS) == suggestion
    result = confirm.execute(
        ConfirmAssociationRequest(
            "prj_proj",
            PROJ_DOCS,
            expected_version=suggestion.version,
            roles=("documentation",),
            acknowledged_shared_with=frozenset({"prj_pay"}),
        )
    )
    assert result.state is AssociationState.CONFIRMED
    assert result.evidence == (REMOTE_LINK,)
